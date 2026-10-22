"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ThemeToggle } from "@/components/AppShell";
import { api } from "@/lib/api";
import type { Theme } from "@/lib/theme";

import { SignUpButton } from "./SignUpButton";

/**
 * Header for the public pages. Renders "Sign in / Sign up" on the server (crawlers
 * and signed-out visitors see it at once); a signed-in visitor gets "Open workspace"
 * once /api/me answers.
 */
export function SiteHeader({ inviteOnly, initialTheme }: { inviteOnly: boolean; initialTheme: Theme }) {
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    let live = true;
    api.me().then((m) => { if (live) setSignedIn(!!m); }).catch(() => {});
    return () => { live = false; };
  }, []);

  const navCls = "hidden min-h-9 items-center rounded-lg px-3 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg md:flex";
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-surface/85 backdrop-blur supports-[backdrop-filter]:bg-surface/75">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <Link href="/" className="flex items-center gap-2 text-base font-semibold text-fg">
          <span aria-hidden="true" className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-xs font-bold text-accent-fg">RT</span>
          Resume Tailor
        </Link>
        <nav aria-label="Main" className="flex flex-wrap items-center gap-2">
          <Link href="/#how-it-works" className={navCls}>How it works</Link>
          <Link href="/#pricing" className={navCls}>Pricing</Link>
          <ThemeToggle initial={initialTheme} />
          {signedIn ? (
            <Link href="/app" className="inline-flex min-h-9 items-center rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg hover:bg-accent-hover">
              Open workspace
            </Link>
          ) : (
            <>
              <Link href="/signin" className="inline-flex min-h-9 items-center rounded-lg px-3 text-sm font-medium text-fg hover:bg-surface-2">
                Sign in
              </Link>
              <SignUpButton inviteOnly={inviteOnly} />
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
