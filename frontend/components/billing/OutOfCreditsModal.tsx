"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { BillingAlert } from "@/components/billing/BillingAlert";
import { BuyButton, planPrice } from "@/components/billing/PlanCard";
import { Button } from "@/components/ui";
import type { OutOfCredits } from "@/lib/api";
import { OUT_OF_CREDITS_EVENT, billingApi, rememberPendingDownload } from "@/lib/billing";
import type { Plan } from "@/lib/schemas";

/**
 * Opens when any API call answers 402: a download that needs paying for, or a tailoring
 * past this month's free ones. Offers the credit pack and the pass, with a plain way
 * out; no countdowns, no pre-selected upsell. For a download, the format is remembered
 * so the buyer comes back from checkout to a download that finishes by itself.
 * Mounted once in AppShell.
 */
export function OutOfCreditsModal() {
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState<OutOfCredits>({ reason: "tailoring" });
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<Element | null>(null);

  useEffect(() => {
    const show = (e: Event) => {
      setWhy((e as CustomEvent<OutOfCredits | undefined>).detail ?? { reason: "tailoring" });
      returnFocus.current = document.activeElement;
      setError(null);
      setOpen(true);
      billingApi.plans()
        .then((p) => setPlans(p.plans.filter((x) => x.kind === "credit_pack" || x.kind === "pass")))
        .catch(setError);
    };
    window.addEventListener(OUT_OF_CREDITS_EVENT, show);
    return () => window.removeEventListener(OUT_OF_CREDITS_EVENT, show);
  }, []);

  useEffect(() => {
    if (!open) return;
    dialog.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      (returnFocus.current as HTMLElement | null)?.focus?.();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-4 sm:items-center"
      onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
      <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="ooc-title" tabIndex={-1}
        className="w-full max-w-md rounded-2xl border border-border bg-surface p-5 shadow-lg outline-none sm:p-6">
        {why.reason === "download" ? (
          <>
            <h2 id="ooc-title" className="text-lg font-semibold">Download your tailored resume</h2>
            <p className="mt-1 text-sm text-muted">
              Tailoring and review are free; the clean file takes a credit or a pass. After paying you&apos;ll come
              back here and the download starts by itself. Re-downloading this resume is free for a week.
            </p>
          </>
        ) : (
          <>
            <h2 id="ooc-title" className="text-lg font-semibold">You&apos;ve used this month&apos;s free tailorings</h2>
            <p className="mt-1 text-sm text-muted">
              To keep tailoring, pick one of these. Credits are only spent when you download a clean file.
            </p>
          </>
        )}
        <p className="mt-1 text-sm text-muted">Both are one-time payments; nothing renews.</p>
        <div className="mt-4 space-y-3">
          <BillingAlert error={error} />
          {plans?.map((plan) => (
            <div key={plan.key} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border p-3">
              <div>
                <p className="text-sm font-medium">{plan.name}</p>
                <p className="text-xs text-muted">
                  {plan.kind === "credit_pack"
                    ? `${plan.credits} credits`
                    : `${plan.pass_days} days, up to ${plan.fair_use_cap} runs`} · {planPrice(plan)}
                </p>
              </div>
              <BuyButton plan={plan} signedIn onError={setError}
                beforeCheckout={why.reason === "download" ? () => rememberPendingDownload(why.fmt) : undefined} />
            </div>
          ))}
        </div>
        <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
          <Link href="/pricing" className="text-sm font-medium text-accent underline" onClick={() => setOpen(false)}>
            Compare all options
          </Link>
          <Button variant="ghost" onClick={() => setOpen(false)}>Not now</Button>
        </div>
      </div>
    </div>
  );
}
