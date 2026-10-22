"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AuthErrorAlert } from "@/components/auth/AuthCard";
import { BillingAlert } from "@/components/billing/BillingAlert";
import { PlanCard } from "@/components/billing/PlanCard";
import { CheckIcon } from "@/components/icons";
import { Card } from "@/components/ui";
import { api } from "@/lib/api";
import { billingApi, freePoints } from "@/lib/billing";
import type { Plans } from "@/lib/schemas";

export default function PricingPage() {
  const [plans, setPlans] = useState<Plans | null>(null);
  const [signedIn, setSignedIn] = useState(false);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [buyError, setBuyError] = useState<unknown>(null);

  useEffect(() => {
    billingApi.plans().then(setPlans).catch(setLoadError);
    api.me().then((m) => setSignedIn(!!m)).catch(() => setSignedIn(false));
  }, []);

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Pricing</h1>
        <p className="mt-1 max-w-2xl text-muted">
          Start free. If you&apos;re applying to a lot of jobs, a credit pack or a pass gives you more runs.
          No subscription unless you choose one.
        </p>
      </div>

      {loadError ? <AuthErrorAlert error={loadError} /> : null}
      <BillingAlert error={buyError} />

      {plans && (
        <>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            <Card as="div" className="flex flex-col" aria-labelledby="plan-free">
              <h2 id="plan-free" className="text-lg font-semibold">Free</h2>
              <p className="mt-2 text-2xl font-semibold tracking-tight">No charge</p>
              <ul className="mt-4 flex-1 space-y-2 text-sm">
                {freePoints(plans.free_analyses_per_month).map((point) => (
                  <li key={point} className="flex gap-2">
                    <CheckIcon className="mt-0.5 h-4 w-4 shrink-0 text-ok" />
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
              <Link href="/app" className="mt-6 inline-flex min-h-10 items-center justify-center rounded-lg border border-border-strong px-4 py-2 text-sm font-medium text-fg hover:bg-surface-2">
                Start tailoring
              </Link>
            </Card>
            {plans.plans.map((plan) => (
              <PlanCard key={plan.key} plan={plan} signedIn={signedIn} onError={setBuyError}
                redownloadDays={plans.redownload_free_days} />
            ))}
          </div>

          <div className="space-y-1 text-sm text-muted">
            <p>
              {plans.prices_include_tax
                ? "Prices include taxes. The exact tax for your location is calculated and shown at checkout."
                : "Taxes, where they apply, are calculated for your location and added at checkout."}{" "}
              You pay in the currency of your billing country.
            </p>
            <p>
              Payments are handled by Dodo Payments, our merchant of record. They process your card or UPI
              payment and send your receipt; your card details never reach us.
            </p>
          </div>
        </>
      )}
    </div>
  );
}

