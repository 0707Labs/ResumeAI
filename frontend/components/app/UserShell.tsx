"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Avatar } from "@/components/app/Avatar";
import { ThemeToggle } from "@/components/AppShell";
import { OutOfCreditsModal } from "@/components/billing/OutOfCreditsModal";
import { CreditsLive } from "@/components/CreditsLive";
import { CardIcon, FileIcon, GiftIcon, HomeIcon, LogOutIcon, MoreIcon, ShieldIcon, UserIcon, WandIcon } from "@/components/icons";
import { api } from "@/lib/api";
import { isStaff } from "@/lib/roles";
import type { Me, PlanStatus } from "@/lib/schemas";
import type { Theme } from "@/lib/theme";
import { planLabel, userApi } from "@/lib/user";

/** Sections of the signed-in area. Downloads and Support join as they're built. The first
 * BOTTOM_BAR are on the phone bottom bar; the rest sit behind its "More". */
export const USER_NAV = [
  { href: "/app/dashboard", label: "Dashboard", Icon: HomeIcon },
  { href: "/app/tailor", label: "Tailor", Icon: WandIcon },
  { href: "/app/resumes", label: "My Resumes", short: "Resumes", Icon: FileIcon },
  { href: "/app/billing", label: "Plan & Billing", short: "Billing", Icon: CardIcon },
  { href: "/app/invites", label: "Invites & Referrals", short: "Invites", Icon: GiftIcon },
  { href: "/app/profile", label: "Profile", Icon: UserIcon },
] as const;
const BOTTOM_BAR = 4;

export const isCurrentSection = (pathname: string, href: string) => pathname === href || pathname.startsWith(`${href}/`);

/**
 * Chrome for /app/*: header (plan, live credits, avatar menu), a sidebar from md up and a
 * bottom bar below it. `me` is null when the backend couldn't be asked during rendering;
 * the pages still work, and every API call is authorized on its own.
 */
export function UserShell({ me, initialTheme, children }: { me: Me | null; initialTheme: Theme; children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="min-h-screen bg-bg">
      <a href="#main" className="sr-only z-50 rounded-lg bg-accent px-4 py-2 text-accent-fg focus:not-sr-only focus:fixed focus:left-4 focus:top-4">
        Skip to main content
      </a>
      <header className="sticky top-0 z-30 border-b border-border bg-surface">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
          <Link href="/app/dashboard" className="text-base font-semibold text-fg">Resume Tailor</Link>
          <div className="flex items-center gap-1 sm:gap-2">
            <PlanChip pathname={pathname} />
            <CreditsLive />
            {me && <AvatarMenu me={me} initialTheme={initialTheme} />}
          </div>
        </div>
      </header>
      <div className="mx-auto flex max-w-7xl gap-6 px-4 pb-24 pt-6 sm:px-6 md:pb-10 md:pt-8">
        <nav aria-label="Sections" className="hidden w-52 shrink-0 md:block">
          <ul className="sticky top-20 space-y-1">
            {USER_NAV.map(({ href, label, Icon }) => {
              const current = isCurrentSection(pathname, href);
              return (
                <li key={href}>
                  <Link href={href} aria-current={current ? "page" : undefined}
                    className={`flex min-h-10 items-center gap-2.5 rounded-lg px-3 text-sm ${
                      current ? "bg-surface-2 font-medium text-fg" : "text-muted hover:bg-surface-2 hover:text-fg"}`}>
                    <Icon />{label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <main id="main" className="min-w-0 flex-1">{children}</main>
      </div>
      <BottomNav pathname={pathname} />
      <OutOfCreditsModal />
    </div>
  );
}

function BottomNav({ pathname }: { pathname: string }) {
  const [open, setOpen] = useState(false);
  const main = USER_NAV.slice(0, BOTTOM_BAR);
  const more = USER_NAV.slice(BOTTOM_BAR);
  const moreCurrent = more.some((i) => isCurrentSection(pathname, i.href));
  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
  const cell = (current: boolean) => `flex min-h-14 w-full flex-col items-center justify-center gap-0.5 px-1 text-[11px] ${
    current ? "font-medium text-accent" : "text-muted hover:text-fg"}`;
  return (
    <nav aria-label="Sections" className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface pb-[env(safe-area-inset-bottom)] md:hidden">
      {open && (
        <ul id="more-sections" className="border-b border-border p-2">
          {more.map((item) => (
            <li key={item.href}>
              <Link href={item.href} aria-current={isCurrentSection(pathname, item.href) ? "page" : undefined}
                className="flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm text-fg hover:bg-surface-2">
                <item.Icon />{item.label}
              </Link>
            </li>
          ))}
        </ul>
      )}
      <ul className="grid grid-cols-5">
        {main.map((item) => {
          const current = isCurrentSection(pathname, item.href);
          return (
            <li key={item.href}>
              <Link href={item.href} aria-current={current ? "page" : undefined} className={cell(current)}>
                <item.Icon className="h-5 w-5" />
                <span className="truncate">{"short" in item ? item.short : item.label}</span>
              </Link>
            </li>
          );
        })}
        <li>
          <button type="button" aria-expanded={open} aria-controls="more-sections" onClick={() => setOpen((o) => !o)}
            className={cell(moreCurrent || open)}>
            <MoreIcon className="h-5 w-5" />
            <span>More</span>
          </button>
        </li>
      </ul>
    </nav>
  );
}

/** Pass days left, Pro, or the free allowance. A credit balance shows through CreditsLive. */
function PlanChip({ pathname }: { pathname: string }) {
  const [plan, setPlan] = useState<PlanStatus | null>(null);
  useEffect(() => {
    let live = true;
    userApi.plan().then((p) => { if (live) setPlan(p); }).catch(() => {});
    return () => { live = false; };
  }, [pathname]);
  if (!plan || plan.kind === "credits") return null;
  return (
    <Link href="/app/billing" data-testid="plan-chip"
      // Pass days and Pro always show; the free allowance only where there's room.
      className={`${plan.kind === "free" ? "hidden sm:flex" : "flex"} min-h-9 items-center rounded-lg px-2 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg sm:px-3`}>
      {planLabel(plan)}
    </Link>
  );
}

function AvatarMenu({ me, initialTheme }: { me: Me; initialTheme: Theme }) {
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  async function signOut() {
    setSigningOut(true);
    try { await api.logout(); } catch { /* the session cookie is cleared server-side when it can be */ }
    router.replace("/");
    router.refresh();
  }

  const item = "flex min-h-10 w-full items-center gap-2 rounded-lg px-3 text-left text-sm text-fg hover:bg-surface-2";
  return (
    <div ref={root} className="relative">
      <button type="button" aria-haspopup="true" aria-expanded={open} aria-controls="account-menu" onClick={() => setOpen((o) => !o)}
        className="rounded-full hover:ring-2 hover:ring-border-strong">
        <Avatar src={me.avatar_url} name={me.name} email={me.email} />
        <span className="sr-only">Account menu</span>
      </button>
      {open && (
        <div id="account-menu" className="absolute right-0 top-11 z-40 w-64 rounded-xl border border-border bg-surface p-2 shadow-lg">
          <div className="border-b border-border px-3 pb-2 pt-1">
            <p className="truncate text-sm font-medium text-fg">{me.name ?? "Your account"}</p>
            <p className="truncate text-xs text-muted">{me.email}</p>
          </div>
          <ul className="space-y-0.5 py-2">
            <li><Link href="/app/profile" className={item}><UserIcon />Profile</Link></li>
            <li><Link href="/app/billing" className={item}><CardIcon />Plan &amp; Billing</Link></li>
            {isStaff(me) && <li><Link href="/admin" className={item}><ShieldIcon />Admin</Link></li>}
          </ul>
          <div className="flex items-center justify-between border-t border-border px-3 py-2">
            <span className="text-xs text-muted">Theme</span>
            <ThemeToggle initial={initialTheme} />
          </div>
          <button type="button" onClick={signOut} disabled={signingOut} className={`${item} border-t border-border`}>
            <LogOutIcon />{signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
      )}
    </div>
  );
}
