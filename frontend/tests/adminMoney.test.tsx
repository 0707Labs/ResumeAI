import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminCostsPage from "@/app/admin/costs/page";
import AdminRevenuePage from "@/app/admin/revenue/page";

const router = { push: vi.fn(), replace: vi.fn() };
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/admin/revenue",
  useSearchParams: () => search,
}));
// Recharts measures its container, which jsdom can't; the table views carry the same numbers.
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
const P1 = "22222222-2222-4222-8222-222222222222";
const AT = "2026-10-20T10:00:00Z";
const me = (capabilities: string[]) => ({ id: U1, email: "a@x.com", name: null, role: "admin", status: "active", capabilities,
  onboarded: true, avatar_url: null });
const CSRF = { "GET /api/auth/csrf": { csrf_token: "tok" } };

const REVENUE = {
  as_of: AT, days: 30, fees_are_estimates: true,
  totals: { gross_usd: 120, refunds_usd: 10, fees_usd: 6.5, net_usd: 110, net_after_fees_usd: 103.5, payments: 12, disputes: 1, unsettled: 2 },
  by_product: [{ product_key: "credits_10", kind: "credit_pack", payments: 12, gross_usd: 120, refunds_usd: 10, fees_usd: 6.5, net_usd: 103.5 }],
  by_currency: [{ currency: "INR", payments: 12, gross_minor: 1200000, refunded_minor: 0 }],
  daily: [{ day: "2026-10-19", gross_usd: 50, net_usd: 45 }, { day: "2026-10-20", gross_usd: 70, net_usd: 58.5 }],
  subscriptions: { active: 4, by_status: { active: 4, cancelled: 1 }, cancelled_in_window: 1, churn_rate: 0.2, renewals_due_7d: 2 },
  referral_liability: { credits_granted_in_window: 6, credits_granted_total: 20, est_value_usd: 6, per_credit_usd: 1 },
};
const PAYMENT = { id: P1, user_id: U1, user_email: "ada@example.com", product_key: "credits_10", kind: "credit_pack", status: "paid",
  mode: "live", currency: "USD", amount_minor: 1000, refunded_amount_minor: 0, provider_payment_id: "pay_1", disputed: false,
  created_at: AT, paid_at: AT };
const PAYMENTS_URL = "GET /api/admin/revenue/payments?page=1&page_size=25";

beforeEach(() => { search = new URLSearchParams(); router.replace.mockReset(); document.cookie = "rt_csrf=tok; path=/"; vi.stubGlobal("ResizeObserver", RO); });
afterEach(() => vi.unstubAllGlobals());

describe("revenue", () => {
  it("shows the totals, the trend as a table, and a refund only to roles that can refund", async () => {
    routes({ "GET /api/me": me(["staff.access", "billing.read"]), "GET /api/admin/revenue?days=30": REVENUE,
      [PAYMENTS_URL]: { items: [PAYMENT], total: 1, page: 1, page_size: 25 } });
    render(<AdminRevenuePage />);
    expect(await screen.findByText("$103.50")).toBeInTheDocument();
    expect(screen.getByText("Fees (estimated)")).toBeInTheDocument();
    expect(screen.getByText("2 payments not settled in USD yet")).toBeInTheDocument();
    const trend = screen.getByRole("table", { name: "Revenue by day" });
    expect(within(trend).getByRole("row", { name: /Oct 20 \$70.00 \$58.50/ })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Legend" })).toHaveTextContent(/Gross.*Net after fees/);
    expect(screen.getByText("20.0%")).toBeInTheDocument();  // churn
    expect(await screen.findByRole("link", { name: "ada@example.com" })).toHaveAttribute("href", `/admin/users/${U1}`);
    expect(screen.queryByRole("button", { name: /^Refund/ })).toBeNull();
  });

  it("refunds part of a payment with a reason", async () => {
    const fetchMock = routes({ ...CSRF, "GET /api/me": me(["staff.access", "billing.read", "billing.write"]),
      "GET /api/admin/revenue?days=30": REVENUE, [PAYMENTS_URL]: { items: [PAYMENT], total: 1, page: 1, page_size: 25 },
      [`POST /api/admin/revenue/payments/${P1}/refund`]: { provider_refund_id: "ref_1", status: "pending" } });
    render(<AdminRevenuePage />);
    await userEvent.click(await screen.findByRole("button", { name: /^Refund ada@example.com/ }));
    await userEvent.type(screen.getByLabelText(/Amount/), "11");
    expect(screen.getByText(/Enter an amount up to \$10/)).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText(/Amount/));
    await userEvent.type(screen.getByLabelText(/Amount/), "2.50");
    await userEvent.type(screen.getByLabelText(/Reason/), "late delivery");
    await userEvent.click(screen.getByRole("button", { name: "Refund part" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Refund requested (pending)");
    expect(bodyOf(fetchMock, `POST /api/admin/revenue/payments/${P1}/refund`)).toEqual({ reason: "late delivery", amount_minor: 250 });
  });

  it("says when a partial refund can't go through", async () => {
    routes({ ...CSRF, "GET /api/me": me(["staff.access", "billing.read", "billing.write"]),
      "GET /api/admin/revenue?days=30": { ...REVENUE, as_of: null }, [PAYMENTS_URL]: { items: [PAYMENT], total: 1, page: 1, page_size: 25 },
      [`POST /api/admin/revenue/payments/${P1}/refund`]: () => json({ detail: "partial_needs_product_id" }, 409) });
    render(<AdminRevenuePage />);
    expect(await screen.findByText("No rollup yet")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: /^Refund ada@example.com/ }));
    await userEvent.type(screen.getByLabelText(/Amount/), "1");
    await userEvent.type(screen.getByLabelText(/Reason/), "goodwill");
    await userEvent.click(screen.getByRole("button", { name: "Refund part" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Dodo product ID");
  });
});

const COSTS = {
  as_of: AT, days: 30, granularity: "day", total_usd: 12.3456, calls: 400, failed_calls: 8, error_rate: 0.02, wasted_usd: 0.4,
  unpriced_calls: 0, free_tier_usd: 3.21,
  series: [{ period: "2026-10-19", cost_usd: 5, calls: 150 }, { period: "2026-10-20", cost_usd: 7.3456, calls: 250 }],
  by_step: [{ key: "tailor", cost_usd: 8, calls: 100 }, { key: "gap_analysis", cost_usd: 4.3456, calls: 300 }],
  by_model: [{ key: "claude-sonnet-5-5", cost_usd: 12.3456, calls: 400 }],
  by_plan: [{ key: "free", cost_usd: 3.21, calls: 100 }],
  per_analysis: { analyses: 100, avg_usd: 0.1234, p95_usd: 0.31 },
  top_users: [{ user_id: U1, email: "ada@example.com", cost_usd: 1.5, calls: 40 }],
  margin: { net_revenue_usd: 103.5, analyses: 100, cost_usd: 12.3456, revenue_per_analysis_usd: 1.035, cost_per_analysis_usd: 0.1235 },
  budget: { today_usd: 8.5, month_usd: 40, daily_budget_usd: 10, monthly_budget_usd: 300, kill_switch: true, paused: null, analyses_paused: false },
  per_user_daily_caps: { free: 10, paid: 30 },
  prices: [{ model: "claude-sonnet-5-5", input: 3, output: 15, cache_read: 0.3, cache_write: 3.75 }],
};
const SETTINGS = { values: { invite_only: false, analyses_paused: false, maintenance_banner: null, invites_per_user: 10,
  signup_bonus_credits: 0, referrals_enabled: true, referral_trigger: "on_first_tailoring", referral_reward_credits: 1,
  referral_monthly_cap: 10, daily_budget_usd: 20, monthly_budget_usd: 300, budget_kill_switch: true }, overridden: [], defaults: {} };

describe("costs", () => {
  it("shows spend against the budgets and where it goes", async () => {
    routes({ "GET /api/me": me(["staff.access", "costs.read"]), "GET /api/admin/costs?days=30&granularity=day": COSTS });
    render(<AdminCostsPage />);
    const today = await screen.findByRole("meter", { name: "Today (UTC)" });
    expect(today).toHaveAttribute("aria-valuetext", "85.0% used: near budget");
    expect(screen.getByText("Analyses running")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "By pipeline step" })).toHaveTextContent(/Tailoring.*\$8.00.*Gap analysis/);
    expect(screen.getByRole("list", { name: "By plan" })).toHaveTextContent("Free tier");
    expect(within(screen.getByRole("table", { name: "Spend by day" })).getByRole("row", { name: /Oct 20 \$7.35/ })).toBeInTheDocument();
    expect(screen.getByText("Changing budgets or the kill switch needs a superadmin.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause analyses now" })).toBeNull();
  });

  it("raises the daily budget with a reason, then reloads", async () => {
    let costs = COSTS;
    const fetchMock = routes({ ...CSRF, "GET /api/me": me(["staff.access", "costs.read", "settings.write"]),
      "GET /api/admin/costs?days=30&granularity=day": () => json(costs),
      "PUT /api/admin/settings/daily_budget_usd": () => { costs = { ...COSTS, budget: { ...COSTS.budget, daily_budget_usd: 20 } }; return json(SETTINGS); } });
    render(<AdminCostsPage />);
    const input = await screen.findByLabelText(/Daily budget/);
    await userEvent.clear(input);
    await userEvent.type(input, "20");
    await userEvent.click(within(input.parentElement!).getByRole("button", { name: "Save" }));
    await userEvent.type(screen.getByLabelText(/Reason/), "launch week");
    await userEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved: Daily budget → $20.00.");
    expect(bodyOf(fetchMock, "PUT /api/admin/settings/daily_budget_usd")).toEqual({ value: 20, reason: "launch week" });
    expect(await screen.findByRole("meter", { name: "Today (UTC)" })).toHaveAttribute("aria-valuetext", "42.5% used: within budget");
  });

  it("says why analyses are paused", async () => {
    routes({ "GET /api/me": me(["staff.access", "costs.read"]), "GET /api/admin/costs?days=30&granularity=day":
      { ...COSTS, unpriced_calls: 3, budget: { ...COSTS.budget, today_usd: 12, paused: "daily_budget" } } });
    render(<AdminCostsPage />);
    expect(await screen.findByText("Paused: daily budget reached")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Today (UTC)" })).toHaveAttribute("aria-valuetext", "120.0% used: over budget");
    expect(screen.getByText("3 calls with no price")).toBeInTheDocument();
  });
});
