"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ThemeToggle } from "@/components/AppShell";
import { BrandLogo } from "@/components/BrandLogo";
import { CloseIcon, MenuIcon } from "@/components/icons";
import { MaintenanceBanner } from "@/components/MaintenanceBanner";
import { api, mightBeSignedIn } from "@/lib/api";
import { SITE_NAV } from "@/lib/site";
import type { Theme } from "@/lib/theme";

import { SignUpButton } from "./SignUpButton";

/**
 * Header for the public pages. Renders "Sign in / Sign up" on the server (crawlers
 * and signed-out visitors see it at once); a signed-in visitor gets "Open workspace"
 * once /api/me answers. Below md the links move into a menu panel; it is only in the
 * DOM while open, so each link exists once.
 */
export function SiteHeader({ inviteOnly, initialTheme }: { inviteOnly: boolean; initialTheme: Theme }) {
  const [signedIn, setSignedIn] = useState(false);
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!mightBeSignedIn()) return;
    let live = true;
    api.me().then((m) => { if (live) setSignedIn(!!m); }).catch(() => {});
    return () => { live = false; };
  }, []);
  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector<HTMLElement>("a, button")?.focus();
    const onKey = (e: KeyboardEvent) => {
      // A modal on top (the invite dialog) handles its own Escape.
      if (e.key !== "Escape" || document.querySelector("dialog[open]")) return;
      setOpen(false);
      toggle.current?.focus();
    };
    // The panel is a phone layout; widening the window past md closes it.
    const wide = window.matchMedia?.("(min-width: 768px)");
    const onWide = () => { if (wide?.matches) setOpen(false); };
    document.addEventListener("keydown", onKey);
    wide?.addEventListener("change", onWide);
    return () => { document.removeEventListener("keydown", onKey); wide?.removeEventListener("change", onWide); };
  }, [open]);

  const link = "inline-flex min-h-9 items-center rounded-lg px-3 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg";
  const primary = "inline-flex min-h-9 items-center justify-center rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg hover:bg-accent-hover";
  const account = (wide: boolean) => signedIn ? (
    <Link href="/app" className={`${primary} ${wide ? "" : "min-h-11 w-full"}`}>Open workspace</Link>
  ) : (
    <>
      <Link href="/signin" className={wide ? "inline-flex min-h-9 items-center rounded-lg px-3 text-sm font-medium text-fg hover:bg-surface-2"
        : "inline-flex min-h-11 w-full items-center justify-center rounded-lg border border-border-strong text-sm font-medium text-fg hover:bg-surface-2"}>
        Sign in
      </Link>
      <SignUpButton inviteOnly={inviteOnly} className={wide ? "" : "min-h-11 w-full"} />
    </>
  );

  return (
    <>
    <MaintenanceBanner />
    <header className="sticky top-0 z-30 border-b border-border bg-surface/85 backdrop-blur supports-[backdrop-filter]:bg-surface/75">
      <div className="mx-auto flex h-16 max-w-(--container) items-center gap-6 px-(--gutter)">
        <Link href="/" className="text-base font-semibold text-fg">
          <BrandLogo />
        </Link>
        <nav aria-label="Main" className="hidden flex-1 items-center gap-1 md:flex">
          {SITE_NAV.map((item) => <Link key={item.href} href={item.href} className={link}>{item.label}</Link>)}
        </nav>
        <div className="ml-auto hidden items-center gap-2 md:flex">
          <ThemeToggle initial={initialTheme} />
          {account(true)}
        </div>
        <button ref={toggle} type="button" aria-expanded={open} aria-controls="site-menu" onClick={() => setOpen((o) => !o)}
          className="ml-auto inline-flex h-10 w-10 items-center justify-center rounded-lg text-fg hover:bg-surface-2 md:hidden">
          {open ? <CloseIcon className="h-5 w-5" /> : <MenuIcon className="h-5 w-5" />}
          <span className="sr-only">{open ? "Close menu" : "Open menu"}</span>
        </button>
      </div>
      {open && (
        <div ref={panel} id="site-menu" className="border-t border-border bg-surface px-(--gutter) pb-5 pt-2 shadow-lg md:hidden">
          <nav aria-label="Main">
            <ul className="divide-y divide-border">
              {SITE_NAV.map((item) => (
                <li key={item.href}>
                  <Link href={item.href} onClick={() => setOpen(false)}
                    className="flex min-h-12 items-center text-base font-medium text-fg hover:text-accent">
                    {item.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <div className="mt-3 grid gap-2">{account(false)}</div>
          <div className="mt-4 flex items-center justify-between">
            <span className="text-sm text-muted">Theme</span>
            <ThemeToggle initial={initialTheme} />
          </div>
        </div>
      )}
    </header>
    </>
  );
}
