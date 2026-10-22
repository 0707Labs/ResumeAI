"use client";

import Link from "next/link";
import { useState } from "react";

import { CheckIcon } from "@/components/icons";
import { Button, Card } from "@/components/ui";
import { billingApi, goTo, planPoints, planPrice, priceList } from "@/lib/billing";
import type { Plan } from "@/lib/schemas";

export { planPoints, planPrice };

/** What a plan gets you, in plain words. Every number comes from the backend catalog. */
/** Starts checkout for one plan: only the product key goes to our backend; the browser
 * then leaves for the provider's hosted payment page. A new key per click, so a double
 * click opens one checkout, never two. */
export function BuyButton({ plan, signedIn, onError, className = "", beforeCheckout }: {
  plan: Plan;
  signedIn: boolean;
  onError: (e: unknown) => void;
  className?: string;
  beforeCheckout?: () => void; // e.g. remember a download to finish after paying
}) {
  const [busy, setBusy] = useState(false);
  const [clickKey] = useState(() => crypto.randomUUID());
  const label = plan.kind === "subscription" ? `Subscribe to ${plan.name}` : `Buy ${plan.name}`;

  if (!plan.available) {
    return <Button variant="secondary" disabled className={className}>Not available yet</Button>;
  }
  if (!signedIn) {
    return (
      <Link href="/signin?next=/pricing"
        className={`inline-flex min-h-10 items-center justify-center rounded-lg border border-border-strong px-4 py-2 text-sm font-medium text-fg hover:bg-surface-2 ${className}`}>
        Sign in to buy
      </Link>
    );
  }
  return (
    <Button busy={busy} className={className} onClick={async () => {
      setBusy(true);
      onError(null);
      try {
        const { checkout_url } = await billingApi.checkout(plan.key, clickKey);
        beforeCheckout?.();
        goTo(checkout_url);
      } catch (e) {
        onError(e);
        setBusy(false);
      }
    }}>
      {label}
    </Button>
  );
}

export function PlanCard({ plan, signedIn, onError, redownloadDays }: {
  plan: Plan;
  signedIn: boolean;
  onError: (e: unknown) => void;
  redownloadDays?: number;
}) {
  return (
    <Card as="div" className="flex flex-col" aria-labelledby={`plan-${plan.key}`}>
      <h2 id={`plan-${plan.key}`} className="text-lg font-semibold">{plan.name}</h2>
      <p className="mt-2 text-2xl font-semibold tracking-tight">{planPrice(plan)}</p>
      <ul className="mt-4 flex-1 space-y-2 text-sm">
        {planPoints(plan, redownloadDays).map((point) => (
          <li key={point} className="flex gap-2">
            <CheckIcon className="mt-0.5 h-4 w-4 shrink-0 text-ok" />
            <span>{point}</span>
          </li>
        ))}
      </ul>
      <BuyButton plan={plan} signedIn={signedIn} onError={onError} className="mt-6 w-full" />
    </Card>
  );
}
