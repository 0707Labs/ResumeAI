/**
 * Sign-in, invite gate and /account calls. Same rules as api.ts: our origin only,
 * every response validated with zod. State-changing calls carry the CSRF header.
 * Failures become AuthError with the backend's short code; authMessage() turns
 * a code into copy for the person in front of the screen.
 */
import type { z } from "zod";

import { API_URL, announceOutOfCredits, csrfToken } from "./api";
import * as S from "./schemas";

export class AuthError extends Error {
  constructor(public code: string, public status: number) {
    super(code);
    this.name = "AuthError";
  }
}

export async function call<T extends z.ZodType>(
  schema: T | null,
  path: string,
  { method = "GET", body, headers: extra }: {
    method?: "GET" | "POST" | "DELETE"; body?: unknown; headers?: Record<string, string>;
  } = {},
): Promise<z.infer<T>> {
  const headers: Record<string, string> = { ...extra };
  if (method !== "GET") headers["X-CSRF-Token"] = await csrfToken();
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
    });
  } catch {
    throw new AuthError("backend_down", 0);
  }
  if (!res.ok) {
    if (res.status === 402) announceOutOfCredits();
    let code = res.status === 422 ? "invalid_input" : res.status === 429 ? "rate_limited" : "server";
    try {
      const detail = (await res.json())?.detail;
      if (typeof detail === "string") code = detail;
    } catch {
      /* not JSON */
    }
    throw new AuthError(code, res.status);
  }
  if (schema === null) return undefined as z.infer<T>;
  const parsed = schema.safeParse(await res.json().catch(() => undefined));
  if (!parsed.success) throw new AuthError("bad_response", res.status);
  return parsed.data;
}

/** Post-sign-in destinations we accept, mirroring the backend's allowlist (app/auth/oauth.py). */
const NEXT_PREFIXES = ["/app", "/account", "/pricing", "/billing", "/admin"];
export const DEFAULT_NEXT = "/app";

/** A same-site path to return to after sign-in, or the workspace. Never another origin. */
export function safeNext(path: string | null | undefined): string {
  if (!path || !/^\/[A-Za-z0-9/_-]*$/.test(path) || path.startsWith("//")) return DEFAULT_NEXT;
  return path === "/" || NEXT_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`)) ? path : DEFAULT_NEXT;
}

// An emailed link opens in a new tab, so the destination waits in localStorage (this
// browser only, a path and a time, nothing else) and is used once within 30 minutes.
const NEXT_KEY = "rt:after-sign-in";
const NEXT_TTL_MS = 30 * 60 * 1000;

export function rememberNext(path: string | undefined) {
  try {
    if (path) localStorage.setItem(NEXT_KEY, JSON.stringify({ path: safeNext(path), at: Date.now() }));
    else localStorage.removeItem(NEXT_KEY);
  } catch { /* storage blocked: they land on the workspace */ }
}

/** The remembered destination (once), or the workspace. */
export function takeNext(): string {
  try {
    const raw = localStorage.getItem(NEXT_KEY);
    localStorage.removeItem(NEXT_KEY);
    const saved = raw ? (JSON.parse(raw) as { path?: string; at?: number }) : null;
    if (saved?.path && typeof saved.at === "number" && Date.now() - saved.at < NEXT_TTL_MS) return safeNext(saved.path);
  } catch { /* fall through */ }
  return DEFAULT_NEXT;
}

/** The page for each step the backend sends us to. */
export const NEXT_PAGE: Record<S.AuthStep["next"], string> = {
  signed_in: "/app",
  invite: "/signup/invite",
  consent: "/signup/consent",
  verify_email: "/signup/verify-email",
  linked: "/account?linked=email",
};

/** Full-page navigation to the provider (OAuth needs a top-level redirect). */
export function providerStartUrl(provider: "google" | "github", opts: { next?: string; link?: boolean } = {}): string {
  const params = new URLSearchParams();
  if (opts.next) params.set("next", opts.next);
  if (opts.link) params.set("intent", "link");
  const qs = params.toString();
  return `${API_URL}/api/auth/${provider}/start${qs ? `?${qs}` : ""}`;
}

export const authApi = {
  providers: () => call(S.ProviderAvailability, "/api/auth/providers"),
  /** Public flags (invite-only). Invite-only is assumed when it can't be read. */
  config: () => call(S.PublicConfig, "/api/auth/config").catch(() => ({ invite_only: true })),
  startEmail: (email: string) => call(S.Accepted, "/api/auth/email/start", { method: "POST", body: { email } }),
  verifyEmail: (token: string) => call(S.AuthStep, "/api/auth/email/verify", { method: "POST", body: { token } }),
  pendingEmail: (email: string) => call(S.Accepted, "/api/auth/pending/email", { method: "POST", body: { email } }),

  /** The sign-in in progress, or null when there is none (expired or never started). */
  async pending(): Promise<S.PendingSignIn | null> {
    try {
      return await call(S.PendingSignIn, "/api/auth/pending");
    } catch (e) {
      if (e instanceof AuthError && e.status === 404) return null;
      throw e;
    }
  },
  /** code omitted: use the invite issued to the verified email. */
  checkInvite: (code?: string) =>
    call(S.AuthStep, "/api/auth/signup/invite", { method: "POST", body: code ? { code } : {} }),
  /** Use the friend's referral link (rt_ref cookie) as the invite. */
  useReferralInvite: () => call(S.AuthStep, "/api/auth/signup/invite", { method: "POST", body: { referral: true } }),
  notices: () => call(S.Notices, "/api/auth/notices"),
  completeSignup: (body: {
    age_18_plus: true;
    accept_terms: true;
    research_opt_in: boolean;
    notice_ids: Partial<Record<"service" | "age_18_plus" | "research", string>>;
  }) => call(S.AuthStep, "/api/auth/signup/complete", { method: "POST", body }),
  joinWaitlist: (email: string, noticeId: string) =>
    call(S.Accepted, "/api/waitlist", { method: "POST", body: { email, age_18_plus: true, notice_id: noticeId } }),

  accountProviders: () => call(S.AccountProviders, "/api/account/providers"),
  unlink: (accountId: string) => call(null, `/api/account/providers/${accountId}`, { method: "DELETE" }),
  linkEmail: (email: string) => call(S.Accepted, "/api/account/email/link", { method: "POST", body: { email } }),
  deleteAccount: () => call(null, "/api/account/delete", { method: "POST", body: { confirm: true } }),
};

type Copy = { title: string; body?: string };

const COPY: Record<string, Copy> = {
  no_invite: {
    title: "No invite found for this account",
    body: "Check the code and try again. If you don't have one yet, you can join the waitlist and we'll email you.",
  },
  email_unverified: {
    title: "Email not verified",
    body: "We only use email addresses your provider has verified. Confirm one with a link we email you.",
  },
  provider_unavailable: {
    title: "Provider unavailable",
    body: "That sign-in option isn't working right now. Try another one, or use an email link.",
  },
  cancelled: { title: "Sign-in cancelled", body: "No problem. Pick a way to continue whenever you're ready." },
  oauth_state: { title: "That sign-in expired", body: "Please start again. It only takes a moment." },
  account_unavailable: {
    title: "This account can't sign in right now",
    body: "If you think this is a mistake, contact us from the grievance page.",
  },
  link_invalid: { title: "This link has expired or was already used", body: "Ask for a new one below." },
  wrong_browser: {
    title: "Open the link in the same browser",
    body: "For your safety, the link only works in the browser where you started signing in.",
  },
  wrong_account: {
    title: "Sign in to the account that asked for this link",
    body: "This link adds email sign-in to a different account than the one signed in here.",
  },
  pending_expired: { title: "Your sign-in timed out", body: "For your safety we only wait 15 minutes. Please start again." },
  invite_required: { title: "An invite is needed first", body: "Enter your invite code to continue." },
  invite_unavailable: {
    title: "That invite was just used up",
    body: "Someone finished signing up with it a moment ago. Try another code, or join the waitlist.",
  },
  stale_notice: { title: "Our terms were just updated", body: "Please read the current version and confirm again." },
  account_exists: { title: "You already have an account", body: "Sign in instead; your existing account is waiting." },
  already_linked_elsewhere: {
    title: "That sign-in belongs to another account",
    body: "It's already connected to a different Resume Tailor account, so we left it there.",
  },
  last_login_method: {
    title: "You need at least one way to sign in",
    body: "Connect another method first, then you can remove this one.",
  },
  not_signed_in: { title: "Please sign in first" },
  rate_limited: { title: "Too many attempts", body: "Please wait a few minutes and try again." },
  email_unavailable: {
    title: "We couldn't send your email",
    body: "Please try again in a few minutes, or sign in with Google or GitHub.",
  },
  csrf_failed: { title: "Please refresh the page", body: "Your session changed in another tab." },
  backend_down: { title: "We can't reach the service", body: "Check your connection and try again." },
  invalid_input: { title: "Please check what you entered" },
};

export function authMessage(err: unknown): Copy {
  const code = err instanceof AuthError ? err.code : typeof err === "string" ? err : "server";
  return COPY[code] ?? { title: "Something went wrong", body: "Please try again in a moment." };
}
