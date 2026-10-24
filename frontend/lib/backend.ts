/**
 * Where the Next.js server reaches FastAPI: the /api/* and /health rewrites (next.config.ts)
 * and the server-side reads in lib/site.ts and lib/session.ts. The browser never sees this
 * URL; it only talks to our own origin, which keeps auth cookies first-party.
 *
 * BACKEND_URL, e.g. http://api.railway.internal:8000 (docs/deploy.md). RT_BACKEND_URL is
 * the old name and still works. Unset means http://localhost:8000, except in a production
 * build or server, which refuses to start rather than proxy to a backend that isn't there.
 */
const DEV_DEFAULT = "http://localhost:8000";

type Env = Record<string, string | undefined>;

export function backendUrl(env: Env = process.env): string {
  const raw = (env.BACKEND_URL || env.RT_BACKEND_URL || "").trim();
  if (!raw) {
    if (env.NODE_ENV === "production") {
      throw new Error("BACKEND_URL must be set for a production build or server (docs/deploy.md)");
    }
    return DEV_DEFAULT;
  }
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`BACKEND_URL is not a URL: ${raw}`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`BACKEND_URL must be http(s): ${raw}`);
  }
  if (url.pathname !== "/" || url.search || url.hash) {
    throw new Error(`BACKEND_URL must be an origin only (no path): ${raw}`);
  }
  return url.origin;
}
