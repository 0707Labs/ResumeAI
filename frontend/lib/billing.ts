/**
 * Billing calls (backend app/api/billing.py). Same rules as auth.ts: our origin only,
 * zod-validated responses, CSRF on state changes. We never send a price, amount or
 * user id: the backend takes those from its catalog and the session.
 */
import { AuthError, authMessage, call } from "./auth";
import * as S from "./schemas";

/** Support address for payment problems, if configured (NEXT_PUBLIC_SUPPORT_EMAIL). */
export const SUPPORT_EMAIL = process.env.NEXT_PUBLIC_SUPPORT_EMAIL ?? "";

/** After checkout: how often and how long we wait for the payment webhook before suggesting support. */
export const POLL_MS = 2000;
export const GIVE_UP_MS = 90_000;

/** Fires when any API call answers 402 (see announceOutOfCredits in api.ts). */
export const OUT_OF_CREDITS_EVENT = "rt:out-of-credits";

export const billingApi = {
  plans: () => call(S.Plans, "/api/billing/plans"),
  checkout: (productKey: string, idempotencyKey: string) =>
    call(S.CheckoutStarted, "/api/billing/checkout", {
      method: "POST",
      body: { product_key: productKey },
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  payment: (paymentId: string) => call(S.PaymentStatus, `/api/billing/payments/${encodeURIComponent(paymentId)}`),
  summary: () => call(S.BillingSummary, "/api/billing/summary"),
  ledger: (before?: number) =>
    call(S.LedgerPage, `/api/billing/ledger${before === undefined ? "" : `?before=${before}`}`),
  portal: () => call(S.PortalLink, "/api/billing/portal", { method: "POST" }),
};

export const adminBillingApi = {
  overview: (days: number) => call(S.AdminOverview, `/api/admin/billing/overview?days=${days}`),
  resolveReview: (id: string) => call(null, `/api/admin/billing/reviews/${encodeURIComponent(id)}/resolve`, { method: "POST" }),
};

/** Leave our site for the provider's hosted page (checkout or portal). */
export function goTo(url: string) {
  window.location.assign(url);
}

/** "₹499" / "$6". Minor units in, the currency's own formatting out. */
export function formatMoney(minor: number, currency: string): string {
  const digits = new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions().maximumFractionDigits ?? 2;
  const value = minor / 10 ** digits;
  return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: Number.isInteger(value) ? 0 : digits,
  }).format(value);
}

/** Prices in a stable order: INR first, then USD, then anything else. */
export function priceList(prices: Record<string, number>): string[] {
  const order = ["INR", "USD"];
  return Object.keys(prices)
    .sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99))
    .map((c) => formatMoney(prices[c], c));
}

const COPY: Record<string, { title: string; body?: string }> = {
  product_unavailable: { title: "This option isn't available right now", body: "Please pick another, or try again later." },
  payments_unavailable: { title: "Payments are switched off right now", body: "Nothing was charged. Please try again later." },
  checkout_failed: { title: "We couldn't open the payment page", body: "Nothing was charged. Please try again." },
  checkout_in_progress: { title: "Your payment page is still being prepared", body: "Give it a moment, then try again." },
  checkout_closed: { title: "That payment page has closed", body: "Start again from the pricing page." },
  portal_unavailable: {
    title: "No receipts yet",
    body: "Receipts and invoices appear in the payment portal after your first purchase.",
  },
  portal_failed: { title: "We couldn't open the payment portal", body: "Please try again in a moment." },
  not_found: { title: "We couldn't find that payment", body: "It may belong to a different account." },
};

export function billingMessage(err: unknown) {
  const code = err instanceof AuthError ? err.code : typeof err === "string" ? err : "server";
  return COPY[code] ?? authMessage(err);
}

export const LEDGER_REASON: Record<string, string> = {
  signup_bonus: "Welcome credits",
  purchase: "Credit pack",
  pass_grant: "Pass credits",
  analysis_charge: "Tailoring run",
  refund: "Credit returned (run didn't finish)",
  referral: "Referral",
  admin_adjust: "Adjustment by support",
  purchase_reversal: "Payment refunded",
};
