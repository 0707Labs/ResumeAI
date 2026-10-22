import type { NextConfig } from "next";

// The browser talks only to this origin; /api/* and /health are proxied to FastAPI.
// Same origin keeps the auth cookies first-party (SameSite=Lax, no CORS credentials).
const BACKEND_URL = (process.env.RT_BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // /signin is the sign-in page; old /login links (bookmarks, emails) keep working.
  async redirects() {
    return [
      { source: "/login", destination: "/signin", permanent: false },
      // The tailoring steps moved under the workspace, then under /app/tailor.
      ...["analysis", "review", "score", "mentor", "export"].flatMap((step) => [
        { source: `/${step}`, destination: `/app/tailor/${step}`, permanent: false },
        { source: `/app/${step}`, destination: `/app/tailor/${step}`, permanent: false },
      ]),
      // Account pages moved into the signed-in area.
      { source: "/account", destination: "/app/profile", permanent: false },
      { source: "/account/billing", destination: "/app/billing", permanent: false },
      { source: "/account/referrals", destination: "/app/invites", permanent: false },
    ];
  },
  // Staff pages stay out of search engines even if a link leaks (robots.ts disallows them too).
  async headers() {
    return [{ source: "/admin/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] }];
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` },
      { source: "/health", destination: `${BACKEND_URL}/health` },
    ];
  },
};

export default nextConfig;
