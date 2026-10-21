/**
 * Referrals: the ?ref= capture, the user's referral page and the header's live updates.
 * Same rules as auth.ts: our origin only, zod-validated, CSRF on state changes.
 */
import { call } from "./auth";
import * as S from "./schemas";

/** Read by the backend at sign-up (app.billing.referrals.COOKIE). */
export const REF_COOKIE = "rt_ref";
const REF_DAYS = 30;
const CODE = /^[A-Z2-9]{8}$/;

/**
 * Keep a referral code from the address bar (?ref=CODE) for sign-up: a first-party cookie
 * (30 days) and a localStorage copy. The first friend's link wins; a later ?ref doesn't
 * overwrite it. Returns the code kept, if any.
 */
export function captureReferral(search: string): string | null {
  const raw = new URLSearchParams(search).get("ref");
  const code = raw?.toUpperCase().replace(/[^A-Z0-9]/g, "") ?? "";
  const existing = currentReferral();
  if (existing) return existing;
  if (!CODE.test(code)) return null;
  document.cookie = `${REF_COOKIE}=${code}; path=/; max-age=${REF_DAYS * 86400}; SameSite=Lax`;
  try { localStorage.setItem(REF_COOKIE, code); } catch { /* storage blocked: the cookie is enough */ }
  return code;
}

export function currentReferral(): string | null {
  const m = new RegExp(`(?:^|; )${REF_COOKIE}=([A-Z2-9]{8})`).exec(document.cookie);
  return m?.[1] ?? null;
}

export const referralsApi = {
  overview: () => call(S.Referrals, "/api/referrals"),
  updates: () => call(S.ReferralUpdates, "/api/referrals/updates"),
  seen: (ids: string[]) => call(null, "/api/referrals/updates/seen", { method: "POST", body: { ids } }),
};

export const adminReferralsApi = {
  queue: (view: "review" | "recent") => call(S.AdminReferrals, `/api/admin/referrals?view=${view}`),
  approve: (id: string) => call(null, `/api/admin/referrals/${encodeURIComponent(id)}/approve`, { method: "POST" }),
  reject: (id: string, reason: string) =>
    call(null, `/api/admin/referrals/${encodeURIComponent(id)}/reject`, { method: "POST", body: { reason } }),
  reverse: (id: string, reason: string) =>
    call(null, `/api/admin/referrals/${encodeURIComponent(id)}/reverse`, { method: "POST", body: { reason } }),
};

/** Plain words for a referral's reason, for the referrer and the admin queue. */
export const REASON_TEXT: Record<string, string> = {
  same_person: "Same person as you",
  disposable_email: "Throwaway email address",
  same_network: "Waiting for a quick review",
  over_monthly_cap: "Over this month's limit",
};
