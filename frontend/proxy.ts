import { type NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIES, isProtected, signInUrl } from "@/lib/workspace";

/**
 * Optimistic gate for the workspace and /admin: no session cookie, straight to /signin.
 * A cookie that exists but is no longer valid is caught by app/app/layout.tsx,
 * and the backend refuses every API call without a live session anyway.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (!isProtected(pathname)) return NextResponse.next();
  if (SESSION_COOKIES.some((name) => request.cookies.get(name)?.value)) return NextResponse.next();
  // The query string can hold only our own step state, never resume text; `next` is checked on use.
  return NextResponse.redirect(new URL(signInUrl(pathname, search), request.url));
}

export const config = {
  matcher: ["/app/:path*", "/admin/:path*"],
};
