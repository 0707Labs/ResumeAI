import { type NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIES, isProtected, signInUrl } from "@/lib/workspace";

/**
 * Optimistic gate for the workspace and /admin: no session cookie, straight to /signin.
 * In development it first moves 127.0.0.1 visits to localhost (toLocalhost).
 * A cookie that exists but is no longer valid is caught by app/app/layout.tsx,
 * and the backend refuses every API call without a live session anyway.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const local = toLocalhost(request);
  if (local) return sendTo(local);
  if (!isProtected(pathname)) return NextResponse.next();
  if (SESSION_COOKIES.some((name) => request.cookies.get(name)?.value)) return NextResponse.next();
  // The query string can hold only our own step state, never resume text; `next` is checked on use.
  return NextResponse.redirect(new URL(signInUrl(pathname, search), request.url));
}

/**
 * Development only: a page opened on 127.0.0.1 (or [::1]) goes to the same address on
 * localhost. Next's dev server blocks its scripts for any other host, so the page would
 * render but never respond (buttons stay disabled), and sign-in cookies and the CSRF check
 * are tied to RT_PUBLIC_URL, which is localhost.
 */
function toLocalhost(request: NextRequest): URL | null {
  if (process.env.NODE_ENV !== "development") return null;
  const host = request.headers.get("host") ?? request.nextUrl.host;
  const match = /^(127\.0\.0\.1|\[::1\])(:\d+)?$/.exec(host);
  if (!match) return null;
  const { pathname, search, protocol } = request.nextUrl;
  return new URL(`${protocol}//localhost${match[2] ?? ""}${pathname}${search}`);
}

/**
 * A page that moves the browser to `url`. Not a 307: Next treats 127.0.0.1 and localhost
 * as the same host and rewrites such a redirect back to a relative one, which loops. A
 * meta refresh needs no JavaScript (the scripts are what's blocked), and the link is there
 * in case refreshes are off.
 */
function sendTo(url: URL): NextResponse {
  const href = url.toString().replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  return new NextResponse(
    `<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=${href}">` +
      `<title>Opening on localhost</title><p>Opening <a href="${href}">${href}</a>…</p>`,
    { status: 200, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } },
  );
}

export const config = {
  // Every page (for the 127.0.0.1 redirect); not Next's own files or the API proxy.
  matcher: ["/((?!_next/|api/|health|favicon.ico|icon.png|apple-icon.png).*)"],
};
