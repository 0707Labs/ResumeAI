/**
 * The admin console's calls (backend app/api/admin*.py). Same rules as auth.ts: our
 * origin, CSRF on writes, every response validated. Every mutation takes a reason,
 * which goes into the audit log.
 */
import { z } from "zod";

import { AuthError, call } from "./auth";
import { reauthUrl } from "./roles";
import * as S from "./schemas";

const qs = (params: Record<string, string | number | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export type UserFilters = { q?: string; status?: string; role?: string; plan?: string; sort?: string; direction?: string; page?: number };

export const adminApi = {
  users: (f: UserFilters) => call(S.AdminUserPage, `/api/admin/users${qs({ ...f, page_size: 25 })}`),
  usersCsvUrl: (f: UserFilters) => `/api/admin/users/export.csv${qs({ ...f, page: undefined })}`,
  user: (id: string) => call(S.AdminUserDetail, `/api/admin/users/${id}`),
  suspend: (id: string, reason: string) => call(null, `/api/admin/users/${id}/suspend`, { method: "POST", body: { reason } }),
  unsuspend: (id: string, reason: string) => call(null, `/api/admin/users/${id}/unsuspend`, { method: "POST", body: { reason } }),
  signOut: (id: string, reason: string) => call(null, `/api/admin/users/${id}/sign-out`, { method: "POST", body: { reason } }),
  adjustCredits: (id: string, delta: number, reason: string) =>
    call(null, `/api/admin/users/${id}/credits`, { method: "POST", body: { delta, reason } }),
  grantPass: (id: string, reason: string, days?: number) =>
    call(null, `/api/admin/users/${id}/pass`, { method: "POST", body: { reason, ...(days ? { days } : {}) } }),
  deleteUser: (id: string, reason: string) => call(null, `/api/admin/users/${id}`, { method: "DELETE", body: { reason } }),

  invites: (f: { status?: string; kind?: string; campaign?: string; q?: string; page?: number }) =>
    call(S.AdminInvitePage, `/api/admin/invites${qs({ ...f, page_size: 25 })}`),
  invitesCsvUrl: (f: { status?: string; kind?: string; campaign?: string }) => `/api/admin/invites/export.csv${qs(f)}`,
  generate: (body: { count: number; max_uses: number; expires_at?: string; email?: string; bonus_credits?: number;
    campaign?: string; note?: string }) => call(S.GeneratedCodes, "/api/admin/invites", { method: "POST", body }),
  revokeInvite: (id: string, reason: string) => call(null, `/api/admin/invites/${id}/revoke`, { method: "POST", body: { reason } }),
  extendInvite: (id: string, expires_at: string, reason: string) =>
    call(null, `/api/admin/invites/${id}/extend`, { method: "POST", body: { expires_at, reason } }),
  funnel: (days = 30) => call(S.InviteFunnel, `/api/admin/invites/funnel?days=${days}`),
  waitlist: (status: string, page = 1) => call(S.WaitlistPage, `/api/admin/waitlist${qs({ status, page })}`),
  approveWaitlist: (ids: string[]) => call(S.ApproveResult, "/api/admin/waitlist/approve", { method: "POST", body: { ids } }),
  rejectWaitlist: (ids: string[], reason: string) => call(null, "/api/admin/waitlist/reject", { method: "POST", body: { ids, reason } }),
  deleteWaitlist: (id: string, reason: string) => call(null, `/api/admin/waitlist/${id}`, { method: "DELETE", body: { reason } }),

  tickets: (f: { status?: string; category?: string; assignee?: string; q?: string; page?: number }) =>
    call(S.AdminTicketPage, `/api/admin/support${qs({ ...f, page_size: 25 })}`),
  ticket: (id: string) => call(S.AdminTicketDetail, `/api/admin/support/${id}`),
  reply: (id: string, body: string) => call(S.TicketMessage, `/api/admin/support/${id}/reply`, { method: "POST", body: { body } }),
  note: (id: string, body: string) => call(S.TicketMessage, `/api/admin/support/${id}/note`, { method: "POST", body: { body } }),
  updateTicket: (id: string, body: { status?: string; assignee_id?: string; unassign?: boolean }) =>
    call(S.AdminTicketRow, `/api/admin/support/${id}`, { method: "PATCH", body }),

  revenue: (days: number) => call(S.AdminRevenue, `/api/admin/revenue?days=${days}`),
  payments: (f: { status?: string; product_key?: string; q?: string; page?: number }) =>
    call(S.AdminPaymentPage, `/api/admin/revenue/payments${qs({ ...f, page_size: 25 })}`),
  refund: (id: string, reason: string, amount_minor?: number) =>
    call(S.RefundResult, `/api/admin/revenue/payments/${id}/refund`, { method: "POST", body: { reason, ...(amount_minor ? { amount_minor } : {}) } }),
  costs: (days: number, granularity: "day" | "week" | "month") =>
    call(S.AdminCosts, `/api/admin/costs${qs({ days, granularity })}`),

  home: (days: number) => call(S.AdminHome, `/api/admin/overview?days=${days}`),
  homeCsvUrl: (days: number) => `/api/admin/overview/export.csv?days=${days}`,
  integrations: () => call(S.Integrations, "/api/admin/integrations"),
  check: (name: string) => call(S.CheckOut, `/api/admin/integrations/${name}/check`, { method: "POST" }),
  webhooks: (status: string, page = 1) => call(S.WebhookPage, `/api/admin/webhooks${qs({ status, page })}`),
  replay: (id: string, reason: string) =>
    call(z.object({ outcome: z.string() }), `/api/admin/webhooks/${encodeURIComponent(id)}/replay`, { method: "POST", body: { reason } }),
  quality: (days: number) => call(S.AdminQuality, `/api/admin/quality?days=${days}`),
  config: () => call(S.AdminConfig, "/api/admin/config"),
  audit: (f: { action?: string; target_type?: string; target_id?: string; actor_id?: string; since?: string; until?: string;
    before_id?: number }) => call(S.AuditPage, `/api/admin/audit${qs({ ...f, limit: 50 })}`),
  staff: () => call(z.array(S.StaffMember), "/api/admin/staff"),
  setRole: (id: string, role: string, reason: string) =>
    call(null, `/api/admin/users/${id}/role`, { method: "PUT", body: { role, reason } }),
  resetSetting: (key: S.SettingKey, reason: string) =>
    call(S.AdminSettings, `/api/admin/settings/${key}/reset`, { method: "POST", body: { reason } }),

  settings: () => call(S.AdminSettings, "/api/admin/settings"),
  setSetting: (key: S.SettingKey, value: unknown, reason: string) =>
    call(S.AdminSettings, `/api/admin/settings/${key}`, { method: "PUT", body: { value, reason } }),
};

/** Words for an admin call that failed. A step-up refusal sends the caller to sign in again. */
export function adminError(err: unknown, path = typeof window === "undefined" ? "/admin" : window.location.pathname): string {
  const code = err instanceof AuthError ? err.code : "server";
  if (code === "reauth_required" && typeof window !== "undefined") {
    window.location.assign(reauthUrl(path));
    return "Sign in again to confirm it's you…";
  }
  const words: Record<string, string> = {
    forbidden: "Your role can't do that.", insufficient_credits: "That would take the balance below zero.",
    deleted: "This account is deleted.", not_staff: "Only staff can be assigned.", email_unavailable:
      "The email couldn't be sent, so nothing was saved. Try again in a minute.",
    email_lock_needs_one_code: "An email-locked invite is a single code.", expiry_in_past: "Pick a date in the future.",
    already_revoked: "That invite is already revoked.", revoked: "That invite is revoked.", no_pass_product: "No pass product is configured.",
    rate_limited: "Too many changes at once. Wait a minute.", invalid_input: "Check the fields: something isn't valid.",
    not_found: "That isn't there any more.", delta_zero: "Enter a non-zero number of credits.",
    not_refundable: "That payment can't be refunded (not paid, or already refunded in full).",
    more_than_paid: "That's more than is left to refund.",
    partial_needs_product_id: "A partial refund needs this product's Dodo product ID in billing.toml. Refund in full, or use Dodo's dashboard.",
    refund_failed: "Dodo didn't accept the refund. Nothing changed here; check Dodo's dashboard.",
    not_replayable: "That event was processed already, or has nothing stored to replay.",
    model_not_allowed: "Pick a model that has a price in billing.toml.",
    own_role: "You can't change your own role.", last_superadmin: "That's the last superadmin: promote someone else first.",
    unknown_setting: "That setting doesn't exist.",
  };
  return words[code] ?? "Something went wrong. Try again.";
}

/** Run an admin call; on failure throw an Error carrying the words to show (ReasonDialog shows them). */
export async function attempt<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (e) {
    throw new Error(adminError(e));
  }
}
