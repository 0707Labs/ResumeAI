"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { captureReferral } from "@/lib/referrals";
import type { Me } from "@/lib/schemas";
import { useSession } from "@/lib/store";
import { THEME_COOKIE, type Theme } from "@/lib/theme";

import { OutOfCreditsModal } from "./billing/OutOfCreditsModal";
import { CreditsLive } from "./CreditsLive";
import { MonitorIcon, MoonIcon, SunIcon, TrashIcon, UserIcon } from "./icons";
import { isResolved } from "./QuestionCard";
import { Button } from "./ui";

/** The landing and legal pages (components/site) and /admin (components/admin) bring their own chrome. */
const isMarketingPath = (path: string) => path === "/" || path === "/legal" || path.startsWith("/legal/");
const isAdminPath = (path: string) => path === "/admin" || path.startsWith("/admin/");
/** The signed-in area has its own shell (components/app/UserShell, from app/app/layout.tsx). */
const isUserAreaPath = (path: string) => path === "/app" || path.startsWith("/app/");

const STEPS = [
  { href: "/app/tailor", label: "Your details" },
  { href: "/app/tailor/analysis", label: "Gaps" },
  { href: "/app/tailor/review", label: "Review" },
  { href: "/app/tailor/score", label: "Score" },
  { href: "/app/tailor/mentor", label: "Mentor" },
  { href: "/app/tailor/export", label: "Export" },
] as const;

/** Restore the session from sessionStorage once, on the client. During server
 * rendering there's no sessionStorage (and no persist API), so this is false. */
export function useHydrated() {
  const [hydrated, setHydrated] = useState(
    () => typeof window !== "undefined" && !!useSession.persist?.hasHydrated(),
  );
  useEffect(() => {
    const persist = useSession.persist;
    if (!persist) return;
    const unsub = persist.onFinishHydration(() => setHydrated(true));
    if (persist.hasHydrated()) setHydrated(true);
    else void persist.rehydrate();
    return unsub;
  }, []);
  return hydrated;
}

export function AppShell({ children, initialTheme }: { children: React.ReactNode; initialTheme: Theme }) {
  useHydrated();
  const pathname = usePathname();
  // A friend's link (?ref=CODE) on any page is kept for sign-up (lib/referrals.ts).
  useEffect(() => { captureReferral(window.location.search); }, [pathname]);
  if (isMarketingPath(pathname) || isAdminPath(pathname) || isUserAreaPath(pathname)) return <>{children}</>;
  return (
    <>
      <a href="#main" className="sr-only z-50 rounded-lg bg-accent px-4 py-2 text-accent-fg focus:not-sr-only focus:fixed focus:left-4 focus:top-4">
        Skip to main content
      </a>
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <Link href="/" className="text-base font-semibold text-fg">Resume Tailor</Link>
          <div className="flex items-center gap-2">
            <Link href="/pricing" className="flex min-h-9 items-center rounded-lg px-3 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg">
              Pricing
            </Link>
            <ThemeToggle initial={initialTheme} />
            <AccountLink pathname={pathname} />
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-8">{children}</main>
      <OutOfCreditsModal />
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs text-muted sm:px-6">
        Your resume stays in this browser tab and is only sent to the Resume Tailor service. No analytics, no tracking.
      </footer>
    </>
  );
}

/** "Sign in" or "Account". Re-checked on each navigation, so it follows sign-in and sign-out. */
function AccountLink({ pathname }: { pathname: string }) {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    api.me().then((m) => { if (live) setMe(m); }).catch(() => { if (live) setMe(null); });
    return () => { live = false; };
  }, [pathname]);
  if (me === undefined) return null;
  const cls = "flex min-h-9 items-center gap-1.5 rounded-lg px-3 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg";
  return me ? (
    <>
      <CreditsLive />
      <Link href="/app/dashboard" className={cls}><UserIcon />Your dashboard</Link>
    </>
  ) : (
    <Link href="/signin" className={cls}>Sign in</Link>
  );
}

export function StepNav() {
  const pathname = usePathname();
  const s = useSession();
  // A step is reachable once the data it needs exists.
  // Review opens once every missing requirement has been answered or skipped,
  // the same rule as the "Continue to tailoring" button.
  const questionsDone = !!s.analysis && s.analysis.items
    .filter((i) => i.status === "missing" && i.question)
    .every((i) => isResolved(s.answers[i.question!.id]));
  const reachable: Record<string, boolean> = {
    "/app/tailor": true,
    "/app/tailor/analysis": !!s.analysis,
    "/app/tailor/review": !!s.tailored || questionsDone,
    "/app/tailor/score": !!s.tailored,
    "/app/tailor/mentor": !!s.analysis,
    "/app/tailor/export": !!s.tailored,
  };
  return (
    <nav aria-label="Progress" className="overflow-x-auto">
      <ol className="flex gap-1 pb-2">
        {STEPS.map((step, i) => {
          const current = pathname === step.href;
          const enabled = reachable[step.href];
          const base = "flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm";
          const num = (
            <span className={`flex h-5 w-5 items-center justify-center rounded-full text-xs ${current ? "bg-accent text-accent-fg" : "bg-surface-2 text-muted"}`}>
              {i + 1}
            </span>
          );
          return (
            <li key={step.href}>
              {enabled ? (
                <Link href={step.href} aria-current={current ? "step" : undefined}
                  className={`${base} ${current ? "font-medium text-fg" : "text-muted hover:bg-surface-2 hover:text-fg"}`}>
                  {num}{step.label}
                </Link>
              ) : (
                <span aria-disabled="true" className={`${base} cursor-not-allowed text-muted/60`}>
                  {num}{step.label}<span className="sr-only"> (not available yet)</span>
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function ThemeToggle({ initial }: { initial: Theme }) {
  const [theme, setTheme] = useState<Theme>(initial);
  const apply = (next: Theme) => {
    setTheme(next);
    const root = document.documentElement;
    if (next === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", next);
    // Only the theme word is stored; nothing about you or your resume.
    document.cookie = next === "system"
      ? `${THEME_COOKIE}=; path=/; max-age=0; SameSite=Lax`
      : `${THEME_COOKIE}=${next}; path=/; max-age=31536000; SameSite=Lax`;
  };
  const options: { value: Theme; label: string; Icon: typeof SunIcon }[] = [
    { value: "system", label: "System theme", Icon: MonitorIcon },
    { value: "light", label: "Light theme", Icon: SunIcon },
    { value: "dark", label: "Dark theme", Icon: MoonIcon },
  ];
  return (
    <div role="radiogroup" aria-label="Color theme" className="flex rounded-lg border border-border p-0.5">
      {options.map(({ value, label, Icon }) => (
        <button key={value} type="button" role="radio" aria-checked={theme === value} aria-label={label} title={label}
          onClick={() => apply(value)}
          className={`rounded-md p-1.5 ${theme === value ? "bg-surface-2 text-fg" : "text-muted hover:text-fg"}`}>
          <Icon />
        </button>
      ))}
    </div>
  );
}

export function ClearAll() {
  const clearAll = useSession((s) => s.clearAll);
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [cleared, setCleared] = useState(false);
  useEffect(() => {
    if (!cleared) return;
    const t = setTimeout(() => setCleared(false), 3000);
    return () => clearTimeout(t);
  }, [cleared]);

  if (confirming) {
    return (
      <div role="group" aria-label="Confirm clearing your data" className="flex items-center gap-1.5">
        <span className="hidden text-sm text-muted sm:inline">Remove everything from this tab?</span>
        <Button variant="danger" className="min-h-9 px-3" onClick={() => { clearAll(); setConfirming(false); setCleared(true); router.replace("/app/tailor"); }}>
          Yes, clear
        </Button>
        <Button variant="ghost" className="min-h-9 px-3" onClick={() => setConfirming(false)} autoFocus>Cancel</Button>
      </div>
    );
  }
  return (
    <>
      <Button variant="ghost" className="min-h-9 px-3" onClick={() => setConfirming(true)}>
        <TrashIcon /> Clear all
      </Button>
      <span role="status" className="sr-only">{cleared ? "Your data was cleared." : ""}</span>
    </>
  );
}
