"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { BillingAlert } from "@/components/billing/BillingAlert";
import { Alert, Card, Spinner } from "@/components/ui";
import { GIVE_UP_MS, POLL_MS, SUPPORT_EMAIL, billingApi, pendingDownload } from "@/lib/billing";
import type { PaymentStatus } from "@/lib/schemas";

const FAILED = new Set(["failed", "cancelled", "checkout_failed"]);
const DONE = new Set(["paid", "partially_refunded", "refunded", "disputed"]);

export default function CheckoutSuccessPage() {
  return (
    <Suspense fallback={null}>
      <CheckoutSuccess />
    </Suspense>
  );
}

/**
 * Where the payment provider sends the buyer back. Its query parameters (status etc.)
 * are not trusted: we only show what our backend says, and the backend grants credits
 * only from the provider's verified webhook. So we poll until that has happened.
 */
function CheckoutSuccess() {
  const paymentId = useSearchParams().get("payment") ?? "";
  const [payment, setPayment] = useState<PaymentStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [gaveUp, setGaveUp] = useState(false);
  const [round, setRound] = useState(0); // bump to start polling again
  const router = useRouter();
  const paid = payment?.status === "paid";
  // Bought to finish a download: once the webhook has granted it, go back and finish it.
  useEffect(() => { if (paid && pendingDownload()) router.replace("/app/tailor/export?resume=download"); }, [paid, router]);

  useEffect(() => {
    if (!paymentId) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const started = Date.now();
    setGaveUp(false);
    const poll = async () => {
      try {
        const p = await billingApi.payment(paymentId);
        if (!live) return;
        setPayment(p);
        setError(null);
        if (DONE.has(p.status) || FAILED.has(p.status)) return;
      } catch (e) {
        if (!live) return;
        setError(e);
        if ((e as { status?: number }).status === 404 || (e as { status?: number }).status === 401) return;
      }
      if (Date.now() - started >= GIVE_UP_MS) setGaveUp(true);
      else timer = setTimeout(poll, POLL_MS);
    };
    void poll();
    return () => { live = false; clearTimeout(timer); };
  }, [paymentId, round]);

  if (!paymentId) {
    return <Centered><Alert tone="warn" title="We don't know which payment this is">
      Your purchases are listed on <Link href="/app/billing" className="font-medium text-accent underline">your billing page</Link>.
    </Alert></Centered>;
  }

  const status = payment?.status;
  return (
    <Centered>
      <Card>
        <h1 className="text-2xl font-semibold tracking-tight">
          {status && DONE.has(status) ? "You're all set" : status && FAILED.has(status) ? "Payment not completed" : "Confirming your payment"}
        </h1>
        <div className="mt-4 space-y-4" aria-live="polite">
          {status && DONE.has(status) && (
            <Alert tone="ok" title="Payment confirmed" role="status">
              {payment!.kind === "credit_pack"
                ? `Your credits are ready. Balance: ${payment!.credits_balance} credits.`
                : payment!.kind === "pass" ? "Your pass is active." : "Your subscription is active."}
            </Alert>
          )}
          {status && FAILED.has(status) && (
            <Alert tone="bad" title="The payment didn't go through" role="alert">
              Nothing was added to your account. If money left your account, it will be returned by your bank;
              you can also try again from the <Link href="/pricing" className="font-medium underline">pricing page</Link>.
            </Alert>
          )}
          {!gaveUp && !(status && (DONE.has(status) || FAILED.has(status))) && !error && (
            <p className="flex items-center gap-2 text-sm text-muted">
              <Spinner label="Checking" />
              {status === "pending"
                ? "Your bank is still confirming the payment. UPI and some cards can take a minute."
                : "Waiting for confirmation from the payment provider. This usually takes a few seconds."}
            </p>
          )}
          <BillingAlert error={error} />
          {(error as { status?: number } | null)?.status === 401 && (
            <p className="text-sm">
              <Link className="font-medium text-accent underline"
                href={`/signin?next=${encodeURIComponent(`/billing/success?payment=${paymentId}`)}`}>
                Sign in to see this payment
              </Link>
            </p>
          )}
          {gaveUp && (
            <Alert tone="warn" title="This is taking longer than usual" role="status">
              <p>
                If you were charged, your purchase will appear as soon as the payment provider confirms it;
                you don&apos;t need to pay again.{" "}
                <button type="button" className="font-medium text-accent underline" onClick={() => setRound((r) => r + 1)}>
                  Check again
                </button>
              </p>
              <p className="mt-2">
                Still missing after a few minutes?{" "}
                {SUPPORT_EMAIL ? (
                  <a className="font-medium text-accent underline"
                    href={`mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(`Payment ${paymentId}`)}`}>
                    Contact support
                  </a>
                ) : "Contact support"}{" "}
                and mention reference <code className="break-all">{paymentId}</code>.
              </p>
            </Alert>
          )}
          <p className="text-sm">
            <Link href="/app/billing" className="font-medium text-accent underline">Go to your billing page</Link>
          </p>
        </div>
      </Card>
    </Centered>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-lg">{children}</div>;
}
