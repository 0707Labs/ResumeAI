import { cookies } from "next/headers";
import type { ReactNode } from "react";

import { getPublicConfig } from "@/lib/site";
import { THEME_COOKIE } from "@/lib/theme";

import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";

/** Chrome for the public pages (/ and /legal/*). AppShell steps aside on these paths. */
export async function PublicPage({ children }: { children: ReactNode }) {
  const [{ invite_only: inviteOnly }, jar] = await Promise.all([getPublicConfig(), cookies()]);
  const saved = jar.get(THEME_COOKIE)?.value;
  const theme = saved === "light" || saved === "dark" ? saved : "system";
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only z-50 rounded-lg bg-accent px-4 py-2 text-accent-fg focus:not-sr-only focus:fixed focus:left-4 focus:top-4">
        Skip to main content
      </a>
      <SiteHeader inviteOnly={inviteOnly} initialTheme={theme} />
      <main id="main" className="flex-1">{children}</main>
      <SiteFooter />
    </div>
  );
}
