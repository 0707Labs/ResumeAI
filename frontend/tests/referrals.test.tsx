import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminReferralsPage from "@/app/admin/referrals/page";
import InvitePage from "@/app/signup/invite/page";
import { CreditsLive } from "@/components/CreditsLive";
import { captureReferral, currentReferral } from "@/lib/referrals";

const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/app/invites",
  useSearchParams: () => new URLSearchParams(),
}));

type Handler = (init?: RequestInit) => Response;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
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

const R1 = "11111111-1111-4111-8111-111111111111";
const R2 = "22222222-2222-4222-8222-222222222222";

beforeEach(() => {
  document.cookie = "rt_csrf=tok; path=/";
  document.cookie = "rt_ref=; max-age=0; path=/";
  localStorage.clear();
  router.replace.mockReset();
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("?ref capture", () => {
  it("keeps a valid code in a first-party cookie, and the first friend's link wins", () => {
    expect(captureReferral("?ref=nope")).toBeNull();
    expect(currentReferral()).toBeNull();
    expect(captureReferral("?ref=abcd-efgh&x=1")).toBe("ABCDEFGH");
    expect(currentReferral()).toBe("ABCDEFGH");
    expect(localStorage.getItem("rt_ref")).toBe("ABCDEFGH");
    expect(captureReferral("?ref=ZZZZZZZZ")).toBe("ABCDEFGH");
  });
});

describe("live credits in the header", () => {
  it("shows the balance and a one-time 'Your friend joined' notice, then marks it seen", async () => {
    const fetchMock = routes({
      "GET /api/referrals/updates": { credits_balance: 3, new_rewards: [{ id: R1, credits: 1, rewarded_at: "2026-10-21T00:00:00Z" }] },
      "GET /api/auth/csrf": { csrf_token: "tok" },
      "POST /api/referrals/updates/seen": () => new Response(null, { status: 204 }),
    });
    render(<CreditsLive />);
    expect(await screen.findByTestId("credits-balance")).toHaveTextContent("3 credits");
    expect(await screen.findByText("Your friend joined. +1 credit")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u) === "/api/referrals/updates/seen"
      && JSON.parse(String(i?.body)).ids[0] === R1)).toBe(true));
  });

  it("polls again, so a reward that lands later shows up", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const answers = [{ credits_balance: 0, new_rewards: [] },
      { credits_balance: 1, new_rewards: [{ id: R2, credits: 1, rewarded_at: "2026-10-21T00:00:00Z" }] }];
    routes({
      "GET /api/referrals/updates": () => json(answers.shift() ?? { credits_balance: 1, new_rewards: [] }),
      "GET /api/auth/csrf": { csrf_token: "tok" },
      "POST /api/referrals/updates/seen": () => new Response(null, { status: 204 }),
    });
    render(<CreditsLive />);
    expect(await screen.findByText("0 credits")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(await screen.findByText("1 credit")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Your friend joined. +1 credit");
  });
});

describe("invite step with a friend's link", () => {
  it("offers the friend's invite and uses it", async () => {
    const fetchMock = routes({
      "GET /api/auth/pending": { kind: "signup", provider: "email", email: "f@example.com", invite_required: true,
        invite_accepted: false, has_bound_invite: false, has_referral_invite: true },
      "GET /api/auth/csrf": { csrf_token: "tok" },
      "POST /api/auth/signup/invite": { next: "consent" },
    });
    render(<InvitePage />);
    await userEvent.click(await screen.findByRole("button", { name: "Use my friend's invite" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/signup/consent"));
    const call = fetchMock.mock.calls.find(([u, i]) => String(u) === "/api/auth/signup/invite" && i?.method === "POST");
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ referral: true });
  });
});

describe("admin referral queue", () => {
  it("is admins only, and approves a flagged referral", async () => {
    const ME = { id: R1, email: "admin@example.com", name: null, role: "admin", status: "active", capabilities: ["staff.access", "referrals.decide"], onboarded: true, avatar_url: null };
    const row = { id: R2, referrer_email: "ada@example.com", referee_email: "f@example.com", status: "pending",
      reason: "same_network", needs_review: true, used_as_invite: false, same_network: 3, reward_credits: 0,
      created_at: "2026-10-21T10:00:00Z", rewarded_at: null, reversed_at: null };
    const fetchMock = routes({
      "GET /api/me": ME,
      "GET /api/admin/referrals?view=review": [row],
      "GET /api/auth/csrf": { csrf_token: "tok" },
      [`POST /api/admin/referrals/${R2}/approve`]: () => new Response(null, { status: 204 }),
    });
    render(<AdminReferralsPage />);
    expect(await screen.findByText(/3 sign-ups from one network/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith(`/${R2}/approve`))).toBe(true));
  });

  it("tells non-admins it isn't for them", async () => {
    routes({ "GET /api/me": { id: R1, email: "u@example.com", name: null, role: "user", status: "active", capabilities: [], onboarded: true, avatar_url: null } });
    render(<AdminReferralsPage />);
    expect(await screen.findByText("Not available for your role")).toBeInTheDocument();
  });
});
