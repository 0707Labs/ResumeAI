import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminIntegrationsPage from "@/app/admin/integrations/page";
import AdminQualityPage from "@/app/admin/quality/page";
import AdminSettingsPage from "@/app/admin/settings/page";
import { Overview } from "@/components/admin/Overview";
import { MaintenanceBanner } from "@/components/MaintenanceBanner";
import { LandingView } from "@/components/site/LandingView";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/admin",
  useSearchParams: () => new URLSearchParams(),
}));
class RO { observe() {} unobserve() {} disconnect() {} }

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
const bodyOf = (fetchMock: ReturnType<typeof routes>, key: string) => {
  const call = fetchMock.mock.calls.filter(([u, i]) => `${i?.method ?? "GET"} ${String(u)}` === key).at(-1);
  return call ? JSON.parse(String(call[1]?.body)) : undefined;
};

const U1 = "11111111-1111-4111-8111-111111111111";
const T1 = "22222222-2222-4222-8222-222222222222";
const AT = "2026-10-20T10:00:00Z";
const CSRF = { "GET /api/auth/csrf": { csrf_token: "tok" } };
const me = (role: string, capabilities: string[]) => ({ id: U1, email: "a@x.com", name: null, role, status: "active", capabilities,
  onboarded: true, avatar_url: null });
const ADMIN = ["staff.access", "users.read", "audit.read", "billing.read", "billing.write", "costs.read", "quality.read", "integrations.read"];
const SUPER = [...ADMIN, "settings.write", "roles.write", "secrets.hint", "users.delete"];

beforeEach(() => { document.cookie = "rt_csrf=tok; path=/"; vi.stubGlobal("ResizeObserver", RO); });
afterEach(() => vi.unstubAllGlobals());

const HOME = {
  days: 30, as_of: AT,
  users: { total: 120, new_7d: 9, new_30d: 40, dau: 12, wau: 50, mau: 90, waitlist: 7, paid: 15 },
  tailorings: { d7: 30, d30: 110 }, open_tickets: 3,
  revenue: { revenue_30d_usd: 420.5, fees_30d_usd: 20, mrr_equivalent_usd: 380, active_pro: 4, credits_sold_30d: 60, credits_consumed_30d: 41 },
  costs: { llm_cost_30d_usd: 55.25, gross_margin: 0.86 },
  series: [{ day: "2026-10-19", signups: 2, revenue_usd: 10, cost_usd: 1.5 }, { day: "2026-10-20", signups: 5, revenue_usd: 30, cost_usd: 2 }],
  funnel: { landing_views: 1000, signups: 40, first_tailoring: 20, downloaded: 10, paid: 5 },
};

describe("overview", () => {
  it("shows KPIs, the money trend and the funnel with step conversion", async () => {
    routes({ "GET /api/admin/overview?days=30": HOME });
    render(<Overview />);
    expect(await screen.findByText("$420.50")).toBeInTheDocument();
    expect(screen.getByText("12 / 50 / 90")).toBeInTheDocument();
    expect(screen.getByText(/Gross margin 86.0%/)).toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "Sign-ups by day" })).getByRole("row", { name: /Oct 20 5/ })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Legend" })).toHaveTextContent(/Revenue.*Claude cost/);
    expect(screen.getByRole("list", { name: "Funnel" })).toHaveTextContent("50.0% of the step before");  // 20 of 40
    expect(screen.getByRole("link", { name: "Export daily CSV" })).toHaveAttribute("href", "/api/admin/overview/export.csv?days=30");
  });

  it("leaves money out for a role that can't see it", async () => {
    routes({ "GET /api/admin/overview?days=30": { ...HOME, revenue: null, costs: null,
      series: HOME.series.map((d) => ({ ...d, revenue_usd: null, cost_usd: null })) } });
    render(<Overview />);
    expect(await screen.findByText("Users")).toBeInTheDocument();
    expect(screen.queryByText(/Revenue \(30 days\)/)).toBeNull();
    expect(screen.queryByRole("table", { name: "Revenue and Claude cost by day" })).toBeNull();
  });
});

const CARDS = [
  { name: "anthropic", status: "configured", checkable: true, checked_at: null, last_ok_at: null, error_code: null, check_detail: {},
    facts: { default_model: "claude-opus-5-5", rate_limited_24h: 2, last_error: { at: AT, status: "rate_limited", code: "api_429" } },
    secrets: [{ name: "ANTHROPIC_API_KEY", set: true, hint: "…ab12" }] },
  { name: "error_monitoring", status: "not_configured", checkable: false, checked_at: null, last_ok_at: null, error_code: null,
    check_detail: {}, facts: { note: "No error monitoring is connected." }, secrets: [] },
];
const SETTINGS = { values: { invite_only: true, analyses_paused: false, maintenance_banner: null, invites_per_user: 10,
  signup_bonus_credits: 0, referrals_enabled: true, referral_trigger: "on_first_tailoring", referral_reward_credits: 1,
  referral_monthly_cap: 10, daily_budget_usd: 20, monthly_budget_usd: 600, budget_kill_switch: true, pro_enabled: false,
  free_analyses_per_month: 2, llm_models: {} }, overridden: [], defaults: { invite_only: true, pro_enabled: false } };
const CONFIG = { products: [{ key: "credit_pack_5", name: "5 credits", kind: "credit_pack", enabled: true, credits: 5, pass_days: null,
  fair_use_cap: null, interval: null, prices: { INR: 49900, USD: 599 } }], free_analyses_per_month: 2, credits_per_download: 1,
  redownload_free_days: 7, claude_per_day: { free: 10, paid: 30 }, retention: { analysis_days: 30, download_days: null },
  llm_prices: ["claude-opus-5-5", "claude-sonnet-5-5"], notices: [{ purpose: "service", version: "v3", language: "en",
    published_at: AT, current: true, body_url: "/legal/terms" }] };
const WEBHOOKS = { items: [{ id: "msg_1", provider: "dodo", event_type: "payment.succeeded", occurred_at: AT, received_at: AT,
  processed_at: null, status: "failing", failures: 3, last_error: "KeyError", replayable: true }], total: 1, page: 1, page_size: 25 };

describe("integrations", () => {
  it("shows status and whether secrets are set, and runs a health check", async () => {
    routes({ ...CSRF, "GET /api/me": me("admin", ADMIN), "GET /api/admin/integrations": CARDS, "GET /api/admin/settings": SETTINGS,
      "GET /api/admin/config": CONFIG, "GET /api/admin/webhooks?status=failing&page=1": WEBHOOKS,
      "POST /api/admin/integrations/anthropic/check": { name: "anthropic", status: "failing", checked_at: AT, last_ok_at: null,
        error_code: "http_401", check_detail: {} } });
    render(<AdminIntegrationsPage />);
    const list = await screen.findByRole("list", { name: "Integrations" });
    const claude = within(list).getByRole("heading", { name: "Claude (Anthropic API)" }).closest("li")!;
    expect(within(claude as HTMLElement).getByText("Configured, not checked")).toBeInTheDocument();
    expect(within(claude as HTMLElement).getByText(/set …ab12/)).toBeInTheDocument();
    expect(within(claude as HTMLElement).getByText("rate_limited · api_429 · " + new Date(AT).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" }))).toBeInTheDocument();
    expect(within(list).getByText("Not configured")).toBeInTheDocument();
    await userEvent.click(within(claude as HTMLElement).getByRole("button", { name: "Run health check" }));
    expect(await within(claude as HTMLElement).findByText("Failing")).toBeInTheDocument();
    expect(within(claude as HTMLElement).getByText("http_401")).toBeInTheDocument();
    expect(screen.getByText(/Changing these needs a superadmin/)).toBeInTheDocument();
  });

  it("lets a superadmin pick a model per step and replay a failed webhook", async () => {
    const fetchMock = routes({ ...CSRF, "GET /api/me": me("superadmin", SUPER), "GET /api/admin/integrations": CARDS,
      "GET /api/admin/settings": SETTINGS, "GET /api/admin/config": CONFIG, "GET /api/admin/webhooks?status=failing&page=1": WEBHOOKS,
      "PUT /api/admin/settings/llm_models": (init?: RequestInit) => json({ ...SETTINGS, values: { ...SETTINGS.values,
        llm_models: JSON.parse(String(init?.body)).value }, overridden: ["llm_models"] }),
      "POST /api/admin/webhooks/msg_1/replay": { outcome: "processed" } });
    render(<AdminIntegrationsPage />);
    await userEvent.selectOptions(await screen.findByLabelText("Tailoring model"), "claude-sonnet-5-5");
    await userEvent.selectOptions(screen.getByLabelText("Tailoring effort"), "low");
    await userEvent.click(screen.getByRole("button", { name: "Save models" }));
    await userEvent.type(screen.getByLabelText(/Reason/), "cheaper tailoring");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(bodyOf(fetchMock, "PUT /api/admin/settings/llm_models")).toEqual({
      value: { tailor: { model: "claude-sonnet-5-5", max_tokens: 16000, effort: "low" } }, reason: "cheaper tailoring" }));
    expect(await screen.findByRole("button", { name: "Back to defaults" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /^Replay payment.succeeded/ }));
    await userEvent.type(screen.getByLabelText(/Reason/), "bug fixed");
    await userEvent.click(screen.getByRole("button", { name: "Replay" }));
    expect(await screen.findByText("Replayed: processed.")).toBeInTheDocument();
    expect(bodyOf(fetchMock, "POST /api/admin/webhooks/msg_1/replay")).toEqual({ reason: "bug fixed" });
  });
});

describe("quality", () => {
  it("shows verifier rates, parse results and fabrication reports", async () => {
    routes({ "GET /api/me": me("admin", ADMIN), "GET /api/admin/quality?days=30": {
      days: 30, verifier: { totals: { bullets_generated: 200, bullets_blocked: 10, bullets_flagged: 30, bullets_approved: 120,
        bullets_rejected: 20, flag_overrides: 6, analyses_tailored: 25, analyses_downloaded: 15 },
        rates: { flagged: 0.15, blocked: 0.0476, override: 0.05 }, trend: [{ day: "2026-10-20", generated: 200, flagged: 30, blocked: 10, overrides: 6 }] },
      parsing: { attempts: 50, ok: 46, failed: { "415": 3, "422": 1 }, failure_rate: 0.08, warnings: { tables_detected: 9 } },
      ats_lift: { buckets: [{ label: "below 0", count: 1 }, { label: "6 to 10", count: 14 }], median: 7 },
      fabrication_reports: [{ id: T1, subject: "Invented a metric", status: "open", analysis_id: null, created_at: AT }] } });
    render(<AdminQualityPage />);
    expect(await screen.findByText("15.0%")).toBeInTheDocument();
    expect(screen.getByText("6 flagged bullets approved anyway")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Parse failures" })).toHaveTextContent(/File type not supported.*3/);
    expect(screen.getByRole("list", { name: "Parse warnings" })).toHaveTextContent("Tables in the file");
    expect(screen.getByRole("list", { name: "ATS lift distribution" })).toHaveTextContent("Lower than before");
    expect(screen.getByRole("link", { name: "Invented a metric" })).toHaveAttribute("href", `/admin/support/${T1}`);
  });
});

const AUDIT = { entries: [{ id: 9, actor_id: U1, actor_email: "boss@x.com", actor_role: "superadmin", action: "settings.update",
  target_type: "setting", target_id: "pro_enabled", reason: "launch", before: { pro_enabled: false }, after: { pro_enabled: true },
  created_at: AT }], next_before_id: null };
const STAFF = [{ id: T1, email: "help@x.com", name: null, role: "support", last_login_at: AT }];

describe("settings", () => {
  it("is read-only for an admin, with the audit log filterable", async () => {
    const fetchMock = routes({ "GET /api/me": me("admin", ADMIN), "GET /api/admin/settings": SETTINGS, "GET /api/admin/config": CONFIG,
      "GET /api/admin/staff": STAFF, "GET /api/admin/audit?limit=50": AUDIT,
      "GET /api/admin/audit?action=settings.update&since=2026-10-01T00%3A00%3A00.000Z&limit=50": AUDIT });
    render(<AdminSettingsPage />);
    expect(await screen.findByText(/Read-only for your role/)).toBeInTheDocument();
    expect(await screen.findByLabelText(/Pro plan on sale/)).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(await screen.findByRole("table", { name: "Products" })).toHaveTextContent("₹499");
    expect(screen.getByRole("list", { name: "Legal versions" })).toHaveTextContent("service v3 (en)");
    expect(within(await screen.findByRole("list", { name: "Staff" })).getByText("Support")).toBeInTheDocument();
    const log = await screen.findByRole("list", { name: "Audit entries" });
    expect(log).toHaveTextContent("pro_enabled: false → pro_enabled: true");
    await userEvent.type(screen.getByLabelText(/^Action/), "settings.update");
    await userEvent.type(screen.getByLabelText("From"), "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: "Filter" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/audit?action=settings.update&since=2026-10-01T00%3A00%3A00.000Z&limit=50", expect.anything()));
  });

  it("lets a superadmin flip a flag and change a role, each with a reason", async () => {
    const fetchMock = routes({ ...CSRF, "GET /api/me": me("superadmin", SUPER), "GET /api/admin/settings": SETTINGS,
      "GET /api/admin/config": CONFIG, "GET /api/admin/staff": STAFF, "GET /api/admin/audit?limit=50": AUDIT,
      "PUT /api/admin/settings/pro_enabled": { ...SETTINGS, values: { ...SETTINGS.values, pro_enabled: true }, overridden: ["pro_enabled"] },
      [`PUT /api/admin/users/${T1}/role`]: () => new Response(null, { status: 204 }) });
    render(<AdminSettingsPage />);
    await userEvent.selectOptions(await screen.findByLabelText(/Pro plan on sale/), "true");
    const row = screen.getByLabelText(/Pro plan on sale/).closest("li")!;
    await userEvent.click(within(row as HTMLElement).getByRole("button", { name: "Save" }));
    await userEvent.type(screen.getByLabelText(/Reason/), "launch");
    await userEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(bodyOf(fetchMock, "PUT /api/admin/settings/pro_enabled")).toEqual({ value: true, reason: "launch" });

    await userEvent.selectOptions(await screen.findByLabelText("Role for help@x.com"), "admin");
    await userEvent.type(screen.getByLabelText(/Reason/), "promoted");
    await userEvent.click(screen.getByRole("button", { name: "Change role" }));
    expect(await screen.findByText("help@x.com is now Admin.")).toBeInTheDocument();
    expect(bodyOf(fetchMock, `PUT /api/admin/users/${T1}/role`)).toEqual({ role: "admin", reason: "promoted" });
  });
});

describe("site-wide", () => {
  it("shows the maintenance banner when staff set one", async () => {
    routes({ "GET /api/auth/config": { invite_only: true, maintenance_banner: "Back at 10:00 UTC." } });
    render(<MaintenanceBanner />);
    expect(await screen.findByRole("status")).toHaveTextContent("Back at 10:00 UTC.");
  });

  it("counts a landing view with a beacon, nothing else", () => {
    const sendBeacon = vi.fn(() => true);
    vi.stubGlobal("navigator", { ...navigator, sendBeacon });
    render(<LandingView />);
    expect(sendBeacon).toHaveBeenCalledWith("/api/metrics/landing-view");
  });
});
