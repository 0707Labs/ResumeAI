"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { BillingAlert } from "@/components/billing/BillingAlert";
import { Alert, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { LEDGER_REASON, billingApi, formatMoney, goTo } from "@/lib/billing";
import type { BillingSummary, LedgerPage, Me } from "@/lib/schemas";

const DATE = new Intl.DateTimeFormat("en", { day: "numeric", month: "short", year: "numeric" });
const date = (iso: string) => DATE.format(new Date(iso));

const PURCHASE_STATUS: Record<string, string> = {
  pending: "Being confirmed",
  paid: "Paid",
  partially_refunded: "Partly refunded",
  refunded: "Refunded",
  disputed: "Under dispute",
};

const SUB_STATUS: Record<string, string> = {
  active: "Active",
  past_due: "Payment overdue: still active while it's retried",
  on_hold: "On hold: renewal payment failed",
  paused: "Paused",
  cancelled: "Cancelled",
  expired: "Ended",
  failed: "Couldn't start",
  pending: "Starting",
};

export default function BillingPage() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [summary, setSummary] = useState<BillingSummary | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.me().then((m) => {
      setMe(m);
      if (m) billingApi.summary().then(setSummary).catch(setError);
    }).catch((e) => { setError(e); setMe(null); });
  }, []);

  if (me === undefined) return null;
  if (me === null) {
    return (
      <div className="mx-auto max-w-md">
        <Alert tone="info" title="Please sign in">
          <Link href="/signin?next=/app/billing" className="font-medium text-accent underline">Sign in</Link> to see your billing.
        </Alert>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Billing</h1>
      </div>
      <BillingAlert error={error} />
      {summary && (
        <>
          <Balance summary={summary} />
          <Purchases summary={summary} onError={setError} />
          <History />
        </>
      )}
    </div>
  );
}

function Balance({ summary }: { summary: BillingSummary }) {
  const { credits_balance: credits, passes, subscription } = summary;
  const nothing = credits === 0 && passes.length === 0 && !subscription;
  return (
    <Card>
      <h2 className="text-lg font-semibold">What you have</h2>
      <dl className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-sm text-muted">Credits</dt>
          <dd className="text-2xl font-semibold">{credits}</dd>
        </div>
        {passes.map((p) => (
          <div key={p.expires_at}>
            <dt className="text-sm text-muted">Job Hunt Pass</dt>
            <dd>
              <span className="text-2xl font-semibold">{p.days_remaining} {p.days_remaining === 1 ? "day" : "days"}</span>{" "}
              <span className="text-sm text-muted">
                left · {new Date(p.starts_at) > new Date() ? `starts ${date(p.starts_at)}, ` : ""}ends {date(p.expires_at)}
              </span>
              <span className="block text-xs text-muted">Fair use: up to {p.analyses_cap} runs</span>
            </dd>
          </div>
        ))}
        {subscription && (
          <div>
            <dt className="text-sm text-muted">Pro subscription</dt>
            <dd className="text-sm">
              <span className="font-medium">{SUB_STATUS[subscription.status] ?? subscription.status}</span>
              {subscription.current_period_end && (
                <span className="block text-muted">
                  {subscription.cancel_at_period_end ? "Ends" : "Renews"} {date(subscription.current_period_end)}
                </span>
              )}
            </dd>
          </div>
        )}
      </dl>
      {nothing && (
        <p className="mt-4 text-sm text-muted">
          You&apos;re on the free plan. <Link href="/pricing" className="font-medium text-accent underline">See options</Link>
        </p>
      )}
    </Card>
  );
}

function Purchases({ summary, onError }: { summary: BillingSummary; onError: (e: unknown) => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <Card>
      <h2 className="text-lg font-semibold">Purchases and receipts</h2>
      {summary.purchases.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No purchases yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-border text-sm">
          {summary.purchases.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
              <span>
                <span className="font-medium">{p.name}</span>
                <span className="block text-xs text-muted">{date(p.paid_at ?? p.created_at)}</span>
              </span>
              <span className="text-right">
                {p.amount_minor !== null && p.currency && <span className="block">{formatMoney(p.amount_minor, p.currency)}</span>}
                <span className="text-xs text-muted">{PURCHASE_STATUS[p.status] ?? p.status}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-sm text-muted">
        Dodo Payments, our merchant of record, issues your receipts and invoices. Open their portal to download
        them{summary.subscription ? " or manage your subscription" : ""}.
      </p>
      <Button variant="secondary" className="mt-3" busy={busy} disabled={!summary.portal_available} onClick={async () => {
        setBusy(true);
        onError(null);
        try {
          goTo((await billingApi.portal()).url);
        } catch (e) {
          onError(e);
          setBusy(false);
        }
      }}>
        Open receipts and invoices
      </Button>
      {!summary.portal_available && (
        <p className="mt-2 text-xs text-muted">Available after your first purchase.</p>
      )}
    </Card>
  );
}

function History() {
  const [pages, setPages] = useState<LedgerPage[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const next = pages.length ? pages[pages.length - 1].next_before : undefined;

  const load = useCallback(async (before?: number) => {
    setBusy(true);
    try {
      const page = await billingApi.ledger(before);
      setPages((ps) => (before === undefined ? [page] : [...ps, page]));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const entries = pages.flatMap((p) => p.entries);
  return (
    <Card>
      <h2 className="text-lg font-semibold">Credit history</h2>
      <BillingAlert error={error} />
      {entries.length === 0 && !busy ? (
        <p className="mt-2 text-sm text-muted">No credit activity yet.</p>
      ) : (
        <table className="mt-3 w-full text-sm">
          <thead className="sr-only">
            <tr><th>Date</th><th>What</th><th>Change</th><th>Balance</th></tr>
          </thead>
          <tbody className="divide-y divide-border">
            {entries.map((e) => (
              <tr key={e.id}>
                <td className="py-2 pr-3 text-muted">{date(e.created_at)}</td>
                <td className="py-2 pr-3">{LEDGER_REASON[e.reason] ?? e.reason}</td>
                <td className="py-2 pr-3 text-right font-medium tabular-nums">{e.delta > 0 ? `+${e.delta}` : e.delta}</td>
                <td className="py-2 text-right text-muted tabular-nums">{e.balance_after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {next != null && (
        <Button variant="ghost" className="mt-2" busy={busy} onClick={() => void load(next)}>Show older</Button>
      )}
    </Card>
  );
}
