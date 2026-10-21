import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BillingPage from "@/app/account/billing/page";
import CheckoutSuccessPage from "@/app/billing/success/page";
import PricingPage from "@/app/pricing/page";
import { OutOfCreditsModal } from "@/components/billing/OutOfCreditsModal";
import { announceOutOfCredits } from "@/lib/api";
import { GIVE_UP_MS, formatMoney } from "@/lib/billing";

const router = { push: vi.fn(), replace: vi.fn() };
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/pricing",
  useSearchParams: () => search,
}));

type Handler = (init?: RequestInit) => Response | Promise<Response>;
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

const ME = { id: "11111111-1111-4111-8111-111111111111", email: "ada@example.com", name: "Ada", role: "user", status: "active" };
const PAYMENT_ID = "22222222-2222-4222-8222-222222222222";
const PACK = { key: "credit_pack_5", kind: "credit_pack", name: "Credit pack", prices: { USD: 600, INR: 49900 },
  credits: 5, pass_days: null, fair_use_cap: null, interval: null, available: true };
const PASS = { key: "job_hunt_pass", kind: "pass", name: "Job Hunt Pass", prices: { INR: 99900, USD: 1200 },
  credits: null, pass_days: 30, fair_use_cap: 40, interval: null, available: true };
const PLANS = { free_analyses_per_month: 2, prices_include_tax: true, plans: [PACK, PASS] };

const assign = vi.fn();
beforeEach(() => {
  search = new URLSearchParams();
  document.cookie = "rt_csrf=tok; path=/";
  assign.mockReset();
  vi.stubGlobal("location", { ...window.location, assign });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  document.cookie = "rt_csrf=; max-age=0; path=/";
});

describe("money", () => {
  it("formats minor units in each currency's style", () => {
    expect(formatMoney(49900, "INR")).toBe("₹499");
    expect(formatMoney(600, "USD")).toBe("$6");
    expect(formatMoney(1250, "USD")).toBe("$12.50");
  });
});

describe("pricing page", () => {
  it("shows free, pack and pass from the catalog with an honest tax note", async () => {
    routes({ "GET /api/billing/plans": PLANS, "GET /api/me": ME });
    render(<PricingPage />);
    const pack = await screen.findByRole("heading", { name: "Credit pack" });
    const card = pack.parentElement!;
    expect(within(card).getByText("₹499 · $6")).toBeInTheDocument();
    expect(within(card).getByText(/5 credits/)).toBeInTheDocument();
    expect(screen.getByText("2 tailoring runs a month")).toBeInTheDocument();
    expect(screen.getByText(/Fair use: up to 40 tailoring runs/)).toBeInTheDocument();
    expect(screen.getByText(/Prices include taxes/)).toBeInTheDocument();
    expect(screen.getByText(/merchant of record/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Pro" })).not.toBeInTheDocument();
  });

  it("sends only the product key, then leaves for the checkout page", async () => {
    const fetchMock = routes({
      "GET /api/billing/plans": PLANS,
      "GET /api/me": ME,
      "POST /api/billing/checkout": { payment_id: PAYMENT_ID, checkout_url: "https://test.checkout.dodopayments.com/c/1" },
    });
    render(<PricingPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Buy Credit pack" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://test.checkout.dodopayments.com/c/1"));
    const [, init] = fetchMock.mock.calls.find(([u]) => String(u) === "/api/billing/checkout")!;
    expect(JSON.parse(String(init!.body))).toEqual({ product_key: "credit_pack_5" });
    const headers = init!.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("tok");
    expect(headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("refuses a non-https checkout URL", async () => {
    routes({
      "GET /api/billing/plans": PLANS,
      "GET /api/me": ME,
      "POST /api/billing/checkout": { payment_id: PAYMENT_ID, checkout_url: "javascript:alert(1)" },
    });
    render(<PricingPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Buy Credit pack" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

  it("asks signed-out visitors to sign in, and marks unavailable plans", async () => {
    routes({
      "GET /api/billing/plans": { ...PLANS, plans: [PACK, { ...PASS, available: false }] },
      "GET /api/me": () => json({ detail: "not_signed_in" }, 401),
    });
    render(<PricingPage />);
    expect(await screen.findByRole("link", { name: "Sign in to buy" })).toHaveAttribute("href", "/login?next=/pricing");
    expect(screen.getByRole("button", { name: "Not available yet" })).toBeDisabled();
  });

  it("explains a checkout failure without leaving the page", async () => {
    routes({
      "GET /api/billing/plans": PLANS,
      "GET /api/me": ME,
      "POST /api/billing/checkout": () => json({ detail: "checkout_failed" }, 502),
    });
    render(<PricingPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Buy Job Hunt Pass" }));
    expect(await screen.findByText("We couldn't open the payment page")).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });
});

describe("checkout success page", () => {
  const status = (s: string) => ({ id: PAYMENT_ID, product_key: "credit_pack_5", kind: "credit_pack", status: s, credits_balance: 5 });

  it("polls until the webhook has granted the purchase, ignoring the provider's query params", async () => {
    search = new URLSearchParams(`payment=${PAYMENT_ID}&status=succeeded`);
    const answers = [status("created"), status("pending"), status("paid")];
    routes({ [`GET /api/billing/payments/${PAYMENT_ID}`]: () => json(answers.shift() ?? status("paid")) });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<CheckoutSuccessPage />);
    expect(await screen.findByText(/Waiting for confirmation/)).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(await screen.findByText(/bank is still confirming/)).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(await screen.findByText(/Balance: 5 credits/)).toBeInTheDocument();
  });

  it("gives up after a while with a support fallback and a retry", async () => {
    search = new URLSearchParams(`payment=${PAYMENT_ID}`);
    const fetchMock = routes({ [`GET /api/billing/payments/${PAYMENT_ID}`]: () => json(status("created")) });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<CheckoutSuccessPage />);
    await act(() => vi.advanceTimersByTimeAsync(GIVE_UP_MS + 2000));
    expect(await screen.findByText("This is taking longer than usual")).toBeInTheDocument();
    expect(screen.getByText(PAYMENT_ID)).toBeInTheDocument();
    const calls = fetchMock.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(calls));
  });

  it("says plainly when a payment failed", async () => {
    search = new URLSearchParams(`payment=${PAYMENT_ID}`);
    routes({ [`GET /api/billing/payments/${PAYMENT_ID}`]: status("failed") });
    render(<CheckoutSuccessPage />);
    expect(await screen.findByText("The payment didn't go through")).toBeInTheDocument();
  });
});

describe("billing page", () => {
  const SUMMARY = {
    credits_balance: 3,
    passes: [{ product_key: "job_hunt_pass", starts_at: "2026-10-01T00:00:00Z", expires_at: "2026-10-31T00:00:00Z",
      days_remaining: 10, analyses_cap: 40 }],
    subscription: null,
    purchases: [{ id: PAYMENT_ID, product_key: "credit_pack_5", name: "Credit pack", status: "paid",
      amount_minor: 49900, currency: "INR", created_at: "2026-10-01T00:00:00Z", paid_at: "2026-10-01T00:00:00Z" }],
    portal_available: true,
  };

  it("shows balance, pass days, purchases and history, and opens the portal", async () => {
    routes({
      "GET /api/me": ME,
      "GET /api/billing/summary": SUMMARY,
      "GET /api/billing/ledger": { entries: [
        { id: 2, delta: -2, reason: "analysis_charge", balance_after: 3, created_at: "2026-10-02T00:00:00Z" },
        { id: 1, delta: 5, reason: "purchase", balance_after: 5, created_at: "2026-10-01T00:00:00Z" },
      ], next_before: 1 },
      "GET /api/billing/ledger?before=1": { entries: [], next_before: null },
      "POST /api/billing/portal": { url: "https://test.customer.dodopayments.com/session/x" },
    });
    render(<BillingPage />);
    expect(await screen.findByText("10 days")).toBeInTheDocument();
    expect(screen.getByText("₹499")).toBeInTheDocument();
    expect(await screen.findByText("Tailoring run")).toBeInTheDocument();
    expect(screen.getByText("+5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show older" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Show older" })).not.toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Open receipts and invoices" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://test.customer.dodopayments.com/session/x"));
  });

  it("asks to sign in when signed out", async () => {
    routes({ "GET /api/me": () => json({ detail: "not_signed_in" }, 401) });
    render(<BillingPage />);
    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login?next=/account/billing");
  });
});

describe("out-of-credits dialog", () => {
  it("opens on a 402, offers pack and pass, and closes without pressure", async () => {
    routes({ "GET /api/billing/plans": PLANS });
    render(<OutOfCreditsModal />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    act(() => announceOutOfCredits());
    const dialog = await screen.findByRole("dialog", { name: "You're out of credits" });
    expect(await within(dialog).findByRole("button", { name: "Buy Credit pack" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Buy Job Hunt Pass" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("billing admin page", () => {
  const OVERVIEW = {
    days: 30,
    payment_counts: { paid: 3, refunded: 1, failed: 2 },
    payments: [{ id: PAYMENT_ID, email: "ada@example.com", product_key: "credit_pack_5", status: "refunded",
      amount_minor: 49900, currency: "INR", refunded_amount_minor: 49900, provider_payment_id: "pay_1",
      created_at: "2026-10-01T00:00:00Z", paid_at: "2026-10-01T00:00:00Z" }],
    credits: { sold: 20, consumed: 7, reversed: 5, outstanding: 8 },
    llm: { calls: 12, total_cost_usd: 0.9, analyses: 4, avg_cost_per_analysis_usd: 0.225, unpriced_calls: 0,
      by_model: [{ model: "claude-opus-5-5", calls: 12, cost_usd: 0.9 }], daily: [{ day: "2026-10-20", cost_usd: 0.9 }] },
    margin: [{ product_key: "credit_pack_5", units: 4, settled_usd_cents: 2032, refunded_usd_cents: 508,
      fees_usd_cents: 160, net_usd_cents: 1364, other_currency_units: 0, runs_if_fully_used: 20,
      llm_cost_if_fully_used_usd_cents: 450, margin_if_fully_used_usd_cents: 914 }],
    fees_are_estimates: true,
    reviews: [{ id: "33333333-3333-4333-8333-333333333333", kind: "credits_already_used", payment_id: PAYMENT_ID,
      detail: { shortfall: 3 }, created_at: "2026-10-02T00:00:00Z" }],
    failing_webhooks: [],
    alerts: [{ kind: "llm_spend", severity: "warning", message: "LLM spend today is $25.00, over the $20.00 threshold." }],
  };

  it("is admins only", async () => {
    routes({ "GET /api/me": ME });
    const { default: AdminPage } = await import("@/app/admin/billing/page");
    render(<AdminPage />);
    expect(await screen.findByText("Admins only")).toBeInTheDocument();
  });

  it("shows alerts, margin, costs and resolves a review", async () => {
    let resolved = false;
    routes({
      "GET /api/me": { ...ME, role: "admin" },
      "GET /api/admin/billing/overview?days=30": () => json(resolved ? { ...OVERVIEW, reviews: [] } : OVERVIEW),
      "POST /api/admin/billing/reviews/33333333-3333-4333-8333-333333333333/resolve": () => {
        resolved = true;
        return new Response(null, { status: 204 });
      },
    });
    const { default: AdminPage } = await import("@/app/admin/billing/page");
    render(<AdminPage />);
    expect(await screen.findByText(/over the \$20.00 threshold/)).toBeInTheDocument();
    expect(screen.getByText("$13.64")).toBeInTheDocument();
    expect(screen.getByText("$0.225")).toBeInTheDocument();
    expect(screen.getByText(/Dodo fees are estimates/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Mark resolved" }));
    expect(await screen.findByText("Nothing to review.")).toBeInTheDocument();
  });
});
