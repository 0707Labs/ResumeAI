import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SignInPage from "@/app/signin/page";
import SignupPage from "@/app/signup/page";
import { AllowanceNote } from "@/components/AllowanceNote";
import { rememberNext, safeNext, takeNext } from "@/lib/auth";
import { proxy } from "@/proxy";

const router = { push: vi.fn(), replace: vi.fn() };
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/signin",
  useSearchParams: () => search,
}));

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const ME = { id: "6f1d2c1e-8a4b-4f7e-9a51-1c2d3e4f5a6b", email: "ada@example.com", name: null, role: "user", status: "active", capabilities: [] };

function stubFetch(table: Record<string, () => Response>) {
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(url)}`;
    if (!(key in table)) throw new Error(`unrouted ${key}`);
    return table[key]();
  }));
}
const SIGNED_OUT = { "GET /api/me": () => json({ detail: "not_signed_in" }, 401) };
const PROVIDERS = { "GET /api/auth/providers": () => json({ google: true, github: true, email: true }) };

beforeEach(() => {
  search = new URLSearchParams();
  router.replace.mockReset();
  localStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("proxy", () => {
  const visit = (path: string, cookie?: string) =>
    proxy(new NextRequest(`http://localhost:3000${path}`, { headers: cookie ? { cookie } : {} }));

  it("sends signed-out visitors of the workspace to /signin with where they were going", () => {
    for (const path of ["/app", "/app/history", "/app/review", "/app/export"]) {
      const res = visit(path);
      expect(res.status).toBe(307);
      expect(res.headers.get("location")).toBe(`http://localhost:3000/signin?next=${encodeURIComponent(path)}`);
    }
  });

  it("lets a request with a session cookie through (the layout and API check it for real)", () => {
    expect(visit("/app", "rt_session=abc").headers.get("location")).toBeNull();
    expect(visit("/app", "__Host-rt_session=abc").headers.get("location")).toBeNull();
    expect(visit("/app", "rt_session=").headers.get("location")).not.toBeNull();
  });

  it("leaves public pages alone", () => {
    for (const path of ["/", "/signin", "/pricing", "/legal/terms", "/application"]) {
      expect(visit(path).headers.get("location")).toBeNull();
    }
  });
});

describe("post-sign-in destination", () => {
  it("accepts only our own workspace and account paths", () => {
    expect(safeNext("/app/review")).toBe("/app/review");
    expect(safeNext("/app")).toBe("/app");
    expect(safeNext("/account/billing")).toBe("/account/billing");
    expect(safeNext("/admin/billing")).toBe("/admin/billing");  // back after a staff re-sign-in
    for (const bad of [undefined, null, "", "//evil.example", "https://evil.example", "/\\evil", "/signin", "/appx", "/adminx"]) {
      expect(safeNext(bad)).toBe("/app");
    }
  });

  it("remembers the destination for an emailed link, once, for 30 minutes", () => {
    rememberNext("/app/review");
    expect(takeNext()).toBe("/app/review");
    expect(takeNext()).toBe("/app");

    vi.useFakeTimers();
    rememberNext("/app/score");
    vi.advanceTimersByTime(31 * 60 * 1000);
    expect(takeNext()).toBe("/app");

    localStorage.setItem("rt:after-sign-in", JSON.stringify({ path: "//evil.example", at: Date.now() }));
    expect(takeNext()).toBe("/app");
  });
});

describe("sign-in screens", () => {
  it("a signed-in visitor skips /signin and goes where they were headed", async () => {
    search = new URLSearchParams("next=/app/review");
    stubFetch({ ...PROVIDERS, "GET /api/me": () => json(ME), "GET /api/auth/config": () => json({ invite_only: true }) });
    render(<SignInPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/app/review"));
  });

  it("an unsafe next sends a signed-in visitor to the workspace instead", async () => {
    search = new URLSearchParams("next=//evil.example");
    stubFetch({ ...PROVIDERS, "GET /api/me": () => json(ME), "GET /api/auth/config": () => json({ invite_only: true }) });
    render(<SignInPage />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/app"));
  });

  it("asking for an email link on /signin?next=… remembers the destination", async () => {
    search = new URLSearchParams("next=/app/review");
    stubFetch({
      ...PROVIDERS, ...SIGNED_OUT,
      "GET /api/auth/config": () => json({ invite_only: true }),
      "GET /api/auth/csrf": () => json({ csrf_token: "tok" }),
      "POST /api/auth/email/start": () => json({ status: "ok" }, 202),
    });
    document.cookie = "rt_csrf=tok; path=/";
    render(<SignInPage />);
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Email me a sign-in link" }));
    await screen.findByRole("status");
    expect(takeNext()).toBe("/app/review");
  });

  it("signup lists the invite step only in invite-only mode, and links Terms and Privacy", async () => {
    stubFetch({ ...PROVIDERS, ...SIGNED_OUT, "GET /api/auth/config": () => json({ invite_only: false }) });
    render(<SignupPage />);
    await waitFor(() => expect(screen.queryByText("Enter your invite code.")).toBeNull());
    expect(screen.queryByRole("link", { name: "Join the waitlist" })).toBeNull();
    expect(screen.getByRole("link", { name: "Terms" })).toHaveAttribute("href", "/legal/terms");
    expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute("href", "/legal/privacy");
  });

  it("signup assumes invite-only when the flag can't be read", async () => {
    stubFetch({ ...PROVIDERS, ...SIGNED_OUT });
    render(<SignupPage />);
    expect(await screen.findByText("Enter your invite code.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Join the waitlist" })).toHaveAttribute("href", "/waitlist");
  });
});

describe("allowance note on /app", () => {
  const allowance = (over: Record<string, unknown>) => ({
    free_allowance: 2, free_used: 0, resets_at: "2026-11-01T00:00:00+00:00", next_uses: "free", credits_balance: 0, ...over,
  });

  it.each([
    [{}, "2 of 2 free tailorings left this month (resets 1 November)."],
    [{ free_used: 2, next_uses: "pass" }, "This tailoring is covered by your Job Hunt Pass."],
    [{ free_used: 2, next_uses: "credit", credits_balance: 3 }, /keep tailoring with your 3 credits; nothing is spent until you download/],
    [{ free_used: 2, next_uses: null }, /used this month's 2 free tailorings \(they reset 1 November\)/],
  ])("says what the next tailoring uses (%o)", async (over, text) => {
    stubFetch({ "GET /api/analyses/allowance": () => json(allowance(over)) });
    render(<AllowanceNote />);
    expect(await screen.findByTestId("allowance")).toHaveTextContent(text);
  });

  it("links to pricing when nothing is left, and shows nothing signed out", async () => {
    stubFetch({ "GET /api/analyses/allowance": () => json(allowance({ free_used: 2, next_uses: null })) });
    const { unmount } = render(<AllowanceNote />);
    expect(await screen.findByRole("link", { name: "Get credits or a pass" })).toHaveAttribute("href", "/pricing");
    unmount();
    stubFetch({ "GET /api/analyses/allowance": () => json({ detail: "not_signed_in" }, 401) });
    const { container } = render(<AllowanceNote />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });
});
