/**
 * Routes that need a signed-in user, shared by proxy.ts (optimistic cookie check)
 * and tests. The real check is server-side: app/app/layout.tsx asks the backend,
 * and every API call is authorized by FastAPI regardless of what the UI shows.
 */
export const PROTECTED_PREFIXES = ["/app", "/analysis", "/review", "/score", "/mentor", "/export"];

export const isProtected = (path: string) =>
  PROTECTED_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`));

/** The backend's session cookie (app/auth/cookies.py): __Host- prefixed over https. */
export const SESSION_COOKIES = ["rt_session", "__Host-rt_session"];

/** Where a signed-out visitor goes, remembering the page they asked for. */
export function signInUrl(path: string, search = ""): string {
  return `/signin?next=${encodeURIComponent(path + search)}`;
}
