"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ThemeToggle } from "@/components/AppShell";
import { ShieldIcon } from "@/components/icons";
import { ROLE_LABEL, sectionsFor } from "@/lib/roles";
import type { Me } from "@/lib/schemas";
import type { Theme } from "@/lib/theme";

/** Staff chrome for /admin: its own header and navigation, separate from the workspace. */
export function AdminShell({ me, initialTheme, children }: { me: Me; initialTheme: Theme; children: React.ReactNode }) {
  const pathname = usePathname();
  const sections = sectionsFor(me);
  const isCurrent = (href: string) => (href === "/admin" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`));
  const linkClass = (href: string) =>
    `flex min-h-9 items-center whitespace-nowrap rounded-lg px-3 text-sm ${
      isCurrent(href) ? "bg-surface-2 font-medium text-fg" : "text-muted hover:bg-surface-2 hover:text-fg"}`;

  return (
    <div className="min-h-screen bg-bg">
      <a href="#admin-main" className="sr-only z-50 rounded-lg bg-accent px-4 py-2 text-accent-fg focus:not-sr-only focus:fixed focus:left-4 focus:top-4">
        Skip to main content
      </a>
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2">
            <Link href="/admin" className="text-base font-semibold text-fg">Resume Tailor</Link>
            <span className="flex items-center gap-1 rounded-md bg-accent-soft px-2 py-0.5 text-xs font-medium text-fg">
              <ShieldIcon />Admin
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden text-sm text-muted sm:inline">
              {me.email} · <span className="font-medium text-fg">{ROLE_LABEL[me.role]}</span>
            </span>
            <ThemeToggle initial={initialTheme} />
            <Link href="/app" className="flex min-h-9 items-center rounded-lg px-3 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg">
              Back to app
            </Link>
          </div>
        </div>
        {/* Small screens: the sections as a scrolling row under the header. */}
        <nav aria-label="Admin sections" className="mx-auto max-w-7xl overflow-x-auto px-4 pb-2 sm:px-6 md:hidden">
          <ul className="flex gap-1">
            {sections.map((s) => (
              <li key={s.href}>
                <Link href={s.href} aria-current={isCurrent(s.href) ? "page" : undefined} className={linkClass(s.href)}>{s.label}</Link>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <div className="mx-auto flex max-w-7xl gap-6 px-4 py-6 sm:px-6 sm:py-8">
        <nav aria-label="Admin sections" className="hidden w-48 shrink-0 md:block">
          <ul className="sticky top-6 space-y-1">
            {sections.map((s) => (
              <li key={s.href}>
                <Link href={s.href} aria-current={isCurrent(s.href) ? "page" : undefined} className={linkClass(s.href)}>{s.label}</Link>
              </li>
            ))}
          </ul>
        </nav>
        <main id="admin-main" className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
