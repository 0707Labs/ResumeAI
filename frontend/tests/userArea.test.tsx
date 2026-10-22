import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DashboardPage from "@/app/app/dashboard/page";
import WelcomePage from "@/app/app/welcome/page";
import { UserShell } from "@/components/app/UserShell";
import { Me, PlanStatus } from "@/lib/schemas";
import { initials, planLabel } from "@/lib/user";

const router = { push: vi.fn(), replace: vi.fn(), refresh: vi.fn() };
let pathname = "/app/dashboard";
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => pathname,
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
const sent = (fetchMock: ReturnType<typeof routes>, key: string) =>
  fetchMock.mock.calls.filter(([u, i]) => `${i?.method ?? "GET"} ${String(u)}` === key);

const ME = Me.parse({ id: "0b6f1d9e-2c4a-4f7b-9d1e-3a5c7e9f1b2d", email: "ada@example.com", name: "Ada Lovelace",
  role: "user", status: "active", capabilities: [], onboarded: true });
const PLAN: PlanStatus = { kind: "free", credits: 0, pass_expires_at: null, pass_days_left: null, pass_downloads_left: null,
  pro_period_end: null, free_allowance: 2, free_left: 1, resets_at: "2026-11-01T00:00:00Z" };
const PREFS = { target_roles: [], seniority: null, industries: [], locations: [], work_modes: [], employment_types: [],
  notice_period_days: null, updated_at: null };
const DASH = {
  name: "Ada Lovelace", plan: PLAN, last_tip: null, has_resume: true, has_preferences: true,
  recent: [{ id: "11111111-1111-4111-8111-111111111111", job_title: "Senior Analyst", company: "Acme",
    created_at: "2026-10-20T10:00:00Z", ats_before: 61.5, ats_after: 78, status: "downloaded" }],
  referrals: { enabled: true, invites_per_user: 5, invites_left: 3, joined: 2, rewarded: 1, credits_earned: 1 },
};
const COMMON = {
  "GET /api/plan": PLAN,
  "GET /api/referrals/updates": { credits_balance: 0, new_rewards: [] },
  "GET /api/auth/csrf": { csrf_token: "tok" },
};

beforeEach(() => { pathname = "/app/dashboard"; Object.values(router).forEach((f) => f.mockReset()); });
afterEach(() => vi.unstubAllGlobals());

describe("helpers", () => {
  it("labels each plan", () => {
    expect(planLabel({ ...PLAN })).toBe("Free · 1 of 2 left");
    expect(planLabel({ ...PLAN, kind: "pass", pass_days_left: 1 })).toBe("Pass · 1 day left");
    expect(planLabel({ ...PLAN, kind: "credits", credits: 3 })).toBe("3 credits");
    expect(planLabel({ ...PLAN, kind: "pro" })).toBe("Pro");
  });

  it("makes initials from the name, else the email", () => {
    expect(initials("Ada  King Lovelace", "a@x.com")).toBe("AL");
    expect(initials("ada", "a@x.com")).toBe("A");
    expect(initials(null, "zed@x.com")).toBe("Z");
  });
});

describe("UserShell", () => {
  it("has the sections in a sidebar and a bottom bar, with the current one marked", () => {
    routes(COMMON);
    pathname = "/app/tailor/review";
    render(<UserShell me={ME} initialTheme="system"><p>page</p></UserShell>);
    const navs = screen.getAllByRole("navigation", { name: "Sections" });
    expect(navs).toHaveLength(2);
    for (const nav of navs) {
      const current = within(nav).getAllByRole("link").filter((a) => a.getAttribute("aria-current") === "page");
      expect(current.map((a) => a.getAttribute("href"))).toEqual(["/app/tailor"]);
    }
    expect(within(navs[0]).getAllByRole("link").map((a) => a.textContent))
      .toEqual(["Dashboard", "Tailor", "Plan & Billing", "Invites & Referrals", "Profile"]);
  });

  it("shows the plan and offers admin only to staff", async () => {
    routes(COMMON);
    const { unmount } = render(<UserShell me={ME} initialTheme="system"><p>page</p></UserShell>);
    expect(await screen.findByTestId("plan-chip")).toHaveTextContent("Free · 1 of 2 left");
    await userEvent.click(screen.getByRole("button", { name: "Account menu" }));
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
    unmount();
    render(<UserShell me={{ ...ME, role: "admin", capabilities: ["staff.access"] }} initialTheme="system"><p /></UserShell>);
    await userEvent.click(screen.getByRole("button", { name: "Account menu" }));
    expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute("href", "/admin");
  });

  it("signs out from the avatar menu", async () => {
    const fetchMock = routes({ ...COMMON, "POST /api/auth/logout": () => new Response(null, { status: 204 }) });
    render(<UserShell me={ME} initialTheme="system"><p /></UserShell>);
    const button = screen.getByRole("button", { name: "Account menu" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(button);
    await userEvent.click(screen.getByRole("button", { name: /Sign out/ }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/"));
    expect(sent(fetchMock, "POST /api/auth/logout")).toHaveLength(1);
  });
});

describe("dashboard", () => {
  it("shows plan, recent tailorings with the ATS change, and referral progress", async () => {
    routes({ "GET /api/dashboard": DASH });
    render(<DashboardPage />);
    expect(await screen.findByRole("heading", { name: "Welcome back, Ada" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Tailor a resume/ })).toHaveAttribute("href", "/app/tailor");
    expect(screen.getByText("Senior Analyst")).toBeInTheDocument();
    expect(screen.getByText(/ATS 62 → 78/)).toHaveTextContent("(up 16)");
    expect(screen.getByText("Downloaded")).toBeInTheDocument();
    expect(screen.getByText("2/5")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See plans" })).toHaveAttribute("href", "/pricing");  // free plan
    expect(screen.queryByText(/Finish setup/)).toBeNull();
  });

  it("has an empty state and a nudge to finish setup", async () => {
    routes({ "GET /api/dashboard": { ...DASH, recent: [], has_resume: false, plan: { ...PLAN, kind: "credits", credits: 2 } } });
    render(<DashboardPage />);
    expect(await screen.findByText("Nothing tailored yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Finish setup" })).toHaveAttribute("href", "/app/welcome");
    expect(screen.queryByRole("link", { name: "See plans" })).toBeNull();
  });

  it("shows a skeleton while loading and lets you retry after an error", async () => {
    let fail = true;
    routes({ "GET /api/dashboard": () => (fail ? json({ detail: "boom" }, 500) : json(DASH)) });
    render(<DashboardPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading your dashboard");
    expect(await screen.findByRole("alert")).toHaveTextContent(/went wrong/);
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Senior Analyst")).toBeInTheDocument();
  });
});

describe("welcome", () => {
  const base = { "GET /api/me": { ...ME, name: "Ada", onboarded: false }, "GET /api/profile/preferences": PREFS,
    "GET /api/auth/csrf": { csrf_token: "tok" } };

  it("saves the name and preferences, then finishes without a resume", async () => {
    const fetchMock = routes({
      ...base,
      "PATCH /api/profile": () => new Response(null, { status: 204 }),
      "PUT /api/profile/preferences": (init?: RequestInit) => json({ ...JSON.parse(String(init?.body)), updated_at: "2026-10-22T00:00:00Z" }),
      "POST /api/profile/onboarded": () => new Response(null, { status: 204 }),
    });
    render(<WelcomePage />);
    const name = await screen.findByLabelText("Your name");
    await waitFor(() => expect(name).toHaveValue("Ada"));
    await userEvent.clear(name);
    await userEvent.type(name, "Ada Lovelace");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    const roles = await screen.findByLabelText(/Target roles/);
    await userEvent.type(roles, "Data Analyst{Enter}BI developer,");
    await userEvent.click(screen.getByRole("checkbox", { name: "Remote" }));
    await userEvent.selectOptions(screen.getByLabelText("Seniority"), "senior");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    await userEvent.click(await screen.findByRole("button", { name: "Do this later" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/app/dashboard"));
    expect(JSON.parse(String(sent(fetchMock, "PATCH /api/profile")[0][1]?.body))).toEqual({ name: "Ada Lovelace" });
    const prefs = JSON.parse(String(sent(fetchMock, "PUT /api/profile/preferences")[0][1]?.body));
    expect(prefs).toMatchObject({ target_roles: ["Data Analyst", "BI developer"], work_modes: ["remote"], seniority: "senior" });
    expect(sent(fetchMock, "POST /api/profile/onboarded")).toHaveLength(1);
  });

  it("can be skipped entirely", async () => {
    const fetchMock = routes({ ...base, "POST /api/profile/onboarded": () => new Response(null, { status: 204 }) });
    render(<WelcomePage />);
    await userEvent.click(await screen.findByRole("button", { name: "Skip setup" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/app/dashboard"));
    expect(sent(fetchMock, "PATCH /api/profile")).toHaveLength(0);
  });

  it("explains a failed save and stays on the step", async () => {
    routes({ ...base, "PUT /api/profile/preferences": () => json({ detail: "rate_limited" }, 429) });
    render(<WelcomePage />);
    await userEvent.click(await screen.findByRole("button", { name: "Skip" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/a lot of changes/);
    expect(screen.getByLabelText(/Target roles/)).toBeInTheDocument();
  });
});
