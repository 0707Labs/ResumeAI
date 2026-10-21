"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { referralsApi } from "@/lib/referrals";

const POLL_MS = 30_000;

/**
 * The signed-in user's credit balance, kept live: polled every 30 seconds and whenever
 * the tab comes back into focus. A referral reward that arrives shows once as
 * "Your friend joined. +1 credit" (then it's marked seen on the server).
 */
export function CreditsLive() {
  const [balance, setBalance] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const busy = useRef(false);

  const refresh = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const u = await referralsApi.updates();
      setBalance(u.credits_balance);
      if (u.new_rewards.length) {
        const credits = u.new_rewards.reduce((n, r) => n + r.credits, 0);
        const friends = u.new_rewards.length;
        setNotice(`${friends === 1 ? "Your friend joined" : `${friends} friends joined`}. +${credits} credit${credits === 1 ? "" : "s"}`);
        await referralsApi.seen(u.new_rewards.map((r) => r.id)).catch(() => {});
      }
    } catch {
      /* signed out or offline: try again on the next tick */
    } finally {
      busy.current = false;
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => { if (document.visibilityState === "visible") void refresh(); }, POLL_MS);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => { clearInterval(timer); window.removeEventListener("focus", onFocus); };
  }, [refresh]);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 8000);
    return () => clearTimeout(t);
  }, [notice]);

  return (
    <>
      {balance !== null && (
        <Link href="/account/billing" data-testid="credits-balance"
          className="flex min-h-9 items-center rounded-lg px-3 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg">
          {balance} credit{balance === 1 ? "" : "s"}
        </Link>
      )}
      <div role="status" aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-50">
        {notice && (
          <div className="pointer-events-auto rounded-xl border border-ok/30 bg-ok-bg px-4 py-3 text-sm font-medium text-ok shadow-lg">
            {notice}
          </div>
        )}
      </div>
    </>
  );
}
