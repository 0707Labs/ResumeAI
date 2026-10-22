import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AccountPage from "@/app/app/profile/page";
import EmailLinkPage from "@/app/auth/email/page";
import SignInPage from "@/app/signin/page";
import ConsentPage from "@/app/signup/consent/page";
import InvitePage from "@/app/signup/invite/page";
import SignupPage from "@/app/signup/page";
import VerifyEmailPage from "@/app/signup/verify-email/page";
import WaitlistPage from "@/app/waitlist/page";
import { AuthError, authMessage } from "@/lib/auth";

const router = { push: vi.fn(), replace: vi.fn() };
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/signin",
  useSearchParams: () => search,
}));

type Handler = (init?: RequestInit) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

/** fetch mock routed by "METHOD path". Unrouted calls fail the test. */
function routes(table: Record<string, Handler | unknown>) {
  const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(url)}`;
    if (!(key in table)) throw new Error(`unrouted ${key}`);
    const entry = table[key];
    return typeof entry === "function" ? (entry as Handler)(init) : json(entry);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const bodyOf = (fetchMock: ReturnType<typeof routes>, key: string) => {
  const call = fetchMock.mock.calls.find(([u, i]) => `${i?.method ?? "GET"} ${String(u)}` === key);
  return JSON.parse(String(call?.[1]?.body));
};

const PENDING = {
  kind: "signup", provider: "github", email: "ada@example.com",
  invite_required: true, invite_accepted: false, has_bound_invite: false,
};
const NOTICES = [
  { id: "11111111-1111-4111-8111-111111111111", purpose: "service", version: "2026-11-v1", body_url: "/legal/terms" },
  { id: "22222222-2222-4222-8222-222222222222", purpose: "age_18_plus", version: "2026-11-v1", body_url: "/legal/age" },
  { id: "33333333-3333-4333-8333-333333333333", purpose: "research", version: "2026-11-v1", body_url: "/legal/research" },
  { id: "44444444-4444-4444-8444-444444444444", purpose: "waitlist", version: "2026-11-v1", body_url: "/legal/waitlist" },
];

beforeEach(() => {
  search = new URLSearchParams();
  router.push.mockReset();
  router.replace.mockReset();
  document.cookie = "rt_csrf=tok; path=/";
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "rt_csrf=; max-age=0; path=/";
});

describe("error copy", () => {
  it.each([
    ["no_invite", "No invite found for this account"],
    ["email_unverified", "Email not verified"],
    ["provider_unavailable", "Provider unavailable"],
  ])("%s -> %s", (code, title) => {
    expect(authMessage(new AuthError(code, 400)).title).toBe(title);
    expect(authMessage(code).title).toBe(title);
  });

  it("never echoes an unknown code back", () => {
    expect(authMessage("<script>x</script>").title).toBe("Something went wrong");
  });
});

describe("login and signup", () => {
  it("offers both providers as full-page links, then an email link", async () => {
    search = new URLSearchParams("next=/review");
    routes({ "GET /api/auth/providers": { google: true, github: true, email: true } });
    render(<SignInPage />);
    const google = await screen.findByRole("link", { name: "Continue with Google" });
    expect(google).toHaveAttribute("href", "/api/auth/google/start?next=%2Freview");
    expect(screen.getByRole("link", { name: "Continue with GitHub" })).toHaveAttribute("href", "/api/auth/github/start?next=%2Freview");
    expect(screen.getByRole("button", { name: "Email me a sign-in link" })).toBeInTheDocument();
  });

  it("shows an unconfigured provider as unavailable, not as a link", async () => {
    routes({ "GET /api/auth/providers": { google: false, github: true, email: true } });
    const { container } = render(<SignupPage />);
    await screen.findByRole("link", { name: "Continue with GitHub" });
    expect(screen.queryByRole("link", { name: /Google/ })).toBeNull();
    const disabled = container.querySelector('[aria-disabled="true"]');
    expect(disabled).toHaveTextContent("Continue with Google");
    expect(disabled).toHaveTextContent("Provider unavailable");
  });

  it("explains an error from the provider redirect", async () => {
    search = new URLSearchParams("error=provider_unavailable");
    routes({ "GET /api/auth/providers": { google: true, github: true, email: true } });
    render(<SignInPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Provider unavailable");
  });

  it("sends a magic link and says where", async () => {
    const fetchMock = routes({
      "GET /api/auth/providers": { google: true, github: true, email: true },
      "POST /api/auth/email/start": () => json({ status: "ok" }, 202),
    });
    render(<SignInPage />);
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Email me a sign-in link" }));
    expect(await screen.findByRole("status")).toHaveTextContent("ada@example.com");
    expect(bodyOf(fetchMock, "POST /api/auth/email/start")).toEqual({ email: "ada@example.com" });
    const init = fetchMock.mock.calls.find(([u]) => String(u) === "/api/auth/email/start")![1]!;
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok");
  });
});

describe("magic link landing", () => {
  it("posts the fragment token once, wipes it from the address bar, and moves on", async () => {
    window.history.replaceState(null, "", "/auth/email#token=secret-token-1234567890");
    const fetchMock = routes({ "POST /api/auth/email/verify": { next: "invite" } });
    render(<StrictMode><EmailLinkPage /></StrictMode>);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/signup/invite"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(bodyOf(fetchMock, "POST /api/auth/email/verify")).toEqual({ token: "secret-token-1234567890" });
    expect(window.location.hash).toBe("");
  });

  it("explains a used or expired link", async () => {
    window.history.replaceState(null, "", "/auth/email#token=old-token-1234567890");
    routes({ "POST /api/auth/email/verify": () => json({ detail: "link_invalid" }, 400) });
    render(<EmailLinkPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("expired or was already used");
  });
});

describe("invite gate", () => {
  it("a wrong code says no invite was found and offers the waitlist", async () => {
    routes({
      "GET /api/auth/pending": PENDING,
      "POST /api/auth/signup/invite": () => json({ detail: "no_invite" }, 400),
    });
    render(<InvitePage />);
    expect(await screen.findByText("ada@example.com")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Invite code/), "WRONG-CODE");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No invite found for this account");
    expect(within(alert).getByRole("link", { name: "Join the waitlist" })).toHaveAttribute("href", "/waitlist");
    expect(router.push).not.toHaveBeenCalled();
  });

  it("a valid code goes on to consent", async () => {
    const fetchMock = routes({ "GET /api/auth/pending": PENDING, "POST /api/auth/signup/invite": { next: "consent" } });
    render(<InvitePage />);
    await userEvent.type(await screen.findByLabelText(/Invite code/), "abcd-efgh-jklm");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/signup/consent"));
    expect(bodyOf(fetchMock, "POST /api/auth/signup/invite")).toEqual({ code: "abcd-efgh-jklm" });
  });

  it("an invite issued to the email can be used without typing a code", async () => {
    const fetchMock = routes({
      "GET /api/auth/pending": { ...PENDING, has_bound_invite: true },
      "POST /api/auth/signup/invite": { next: "consent" },
    });
    render(<InvitePage />);
    await userEvent.click(await screen.findByRole("button", { name: "Use my invite" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/signup/consent"));
    expect(bodyOf(fetchMock, "POST /api/auth/signup/invite")).toEqual({});
  });

  it("an expired sign-in starts over", async () => {
    routes({ "GET /api/auth/pending": () => json({ detail: "pending_expired" }, 404) });
    render(<InvitePage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Your sign-in timed out");
  });

  it("no verified email: the verify page says so", async () => {
    routes({ "GET /api/auth/pending": { ...PENDING, kind: "needs_email", email: null } });
    render(<VerifyEmailPage />);
    expect(await screen.findByText("Email not verified")).toBeInTheDocument();
    expect(screen.getByText(/GitHub account didn.t share a verified email/)).toBeInTheDocument();
  });
});

describe("consent", () => {
  const ready = { ...PENDING, invite_accepted: true };

  it("requires 18+ and terms; research stays off unless ticked", async () => {
    const fetchMock = routes({
      "GET /api/auth/pending": ready,
      "GET /api/auth/notices": NOTICES,
      "POST /api/auth/signup/complete": { next: "signed_in" },
    });
    render(<ConsentPage />);
    const create = await screen.findByRole("button", { name: "Create my account" });
    const research = screen.getByRole("checkbox", { name: /Help improve the product/ });
    expect(research).not.toBeChecked();
    expect(create).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /18 years of age or older/ }));
    expect(create).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Terms of Service and Privacy Policy/ }));
    expect(create).toBeEnabled();
    expect(screen.getByRole("link", { name: "Terms of Service and Privacy Policy" })).toHaveAttribute("href", "/legal/terms");

    await userEvent.click(create);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/app"));
    expect(bodyOf(fetchMock, "POST /api/auth/signup/complete")).toEqual({
      age_18_plus: true, accept_terms: true, research_opt_in: false,
      notice_ids: { service: NOTICES[0].id, age_18_plus: NOTICES[1].id },
    });
  });

  it("sends the research notice only when ticked", async () => {
    const fetchMock = routes({
      "GET /api/auth/pending": ready,
      "GET /api/auth/notices": NOTICES,
      "POST /api/auth/signup/complete": { next: "signed_in" },
    });
    render(<ConsentPage />);
    await userEvent.click(await screen.findByRole("checkbox", { name: /18 years/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Terms of Service/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Help improve the product/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create my account" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalled());
    const body = bodyOf(fetchMock, "POST /api/auth/signup/complete");
    expect(body.research_opt_in).toBe(true);
    expect(body.notice_ids.research).toBe(NOTICES[2].id);
  });

  it("goes back to the invite step until an invite is accepted", async () => {
    routes({ "GET /api/auth/pending": PENDING, "GET /api/auth/notices": NOTICES });
    render(<ConsentPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/signup/invite"));
  });

  it("stays on consent when signup is open and no invite is needed", async () => {
    routes({ "GET /api/auth/pending": { ...PENDING, invite_required: false }, "GET /api/auth/notices": NOTICES });
    render(<ConsentPage />);
    expect(await screen.findByRole("button", { name: "Create my account" })).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });
});

describe("waitlist", () => {
  it("pre-fills the email from the sign-in in progress and needs the 18+ box", async () => {
    const fetchMock = routes({
      "GET /api/auth/pending": PENDING,
      "GET /api/auth/notices": NOTICES,
      "POST /api/waitlist": () => json({ status: "ok" }, 202),
    });
    render(<WaitlistPage />);
    await waitFor(() => expect(screen.getByLabelText("Email")).toHaveValue("ada@example.com"));
    const join = screen.getByRole("button", { name: "Join the waitlist" });
    expect(join).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /18 years/ }));
    await userEvent.click(join);
    expect(await screen.findByText("You're on the list")).toBeInTheDocument();
    expect(bodyOf(fetchMock, "POST /api/waitlist")).toEqual({
      email: "ada@example.com", age_18_plus: true, notice_id: NOTICES[3].id,
    });
  });
});

describe("account", () => {
  const ME = { id: "0b6f1d9e-2c4a-4f7b-9d1e-3a5c7e9f1b2d", email: "ada@example.com", name: null, role: "user", status: "active", capabilities: [], onboarded: true };
  const account = (id: string, provider: string) =>
    ({ id, provider, email: "ada@example.com", linked_at: "2026-10-21T00:00:00Z" });
  const A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  const B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

  it("can't disconnect the last way to sign in", async () => {
    routes({
      "GET /api/me": ME,
      "GET /api/account/providers": { accounts: [account(A, "email")], can_unlink: false,
        available: { google: true, github: false, email: true } },
    });
    render(<AccountPage />);
    expect(await screen.findByRole("button", { name: /Disconnect Email link/ })).toBeDisabled();
    expect(screen.getByText(/only way to sign in/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect Google" })).toHaveAttribute("href", "/api/auth/google/start?intent=link");
    expect(screen.queryByRole("link", { name: "Connect GitHub" })).toBeNull(); // not configured
  });

  it("disconnects one of two and shows a refusal from the server", async () => {
    const fetchMock = routes({
      "GET /api/me": ME,
      "GET /api/account/providers": { accounts: [account(A, "email"), account(B, "google")], can_unlink: true,
        available: { google: true, github: true, email: true } },
      [`DELETE /api/account/providers/${B}`]: () => json({ detail: "last_login_method" }, 409),
    });
    render(<AccountPage />);
    await userEvent.click(await screen.findByRole("button", { name: /Disconnect Google/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You need at least one way to sign in");
    const init = fetchMock.mock.calls.find(([u]) => String(u).endsWith(B))![1]!;
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok");
  });

  it("asks signed-out visitors to sign in", async () => {
    routes({ "GET /api/me": () => json({ detail: "not_signed_in" }, 401) });
    render(<AccountPage />);
    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/signin?next=/app/profile");
  });
});
