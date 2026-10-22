/**
 * The admin console's calls (backend app/api/admin*.py). Same rules as auth.ts: our
 * origin, CSRF on writes, every response validated. Every mutation takes a reason,
 * which goes into the audit log.
 */
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
