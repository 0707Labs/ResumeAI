"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { BillingAlert } from "@/components/billing/BillingAlert";
import { Alert, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { can } from "@/lib/roles";
import { adminBillingApi, formatMoney } from "@/lib/billing";
import type { AdminOverview, Me } from "@/lib/schemas";

const RANGES = [7, 30, 90] as const;
const usd = (cents: number | null) => (cents === null ? "n/a" : formatMoney(cents, "USD"));
const dollars = (v: number | null, digits = 2) => (v === null ? "n/a" : `$${v.toFixed(digits)}`);
const when = (iso: string) => new Date(iso).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" });

const REVIEW_LABEL: Record<string, string> = {
  credits_already_used: "Refund after credits were spent",
  partial_refund: "Partial refund to check",
  dispute_opened: "Dispute opened",
  payment_mismatch: "Payment didn't match checkout",
  unknown_payment: "Payment we have no record of",
  user_missing: "Paid by a deleted account",
};

export default function AdminBillingPage() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback((d: number) => {
    setError(null);
    adminBillingApi.overview(d).then(setData).catch(setError);
  }, []);
  useEffect(() => {
    api.me().then((m) => { setMe(m); if (can(m, "billing.read")) load(days); }).catch(() => setMe(null));
  }, [days, load]);

  if (me === undefined) return null;
  if (!can(me, "billing.read")) {
    return (
      <div className="mx-auto max-w-md">
        <Alert tone="info" title="Not available for your role">
          Billing needs an admin. <Link href="/admin" className="font-medium text-accent underline">Back to admin</Link>
        </Alert>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Billing admin</h1>
          <p className="mt-1 text-sm text-muted">Payments, credits, LLM cost and margin. Amounts in USD unless shown otherwise.</p>
        </div>
        <div role="group" aria-label="Date range" className="flex gap-1">
          {RANGES.map((r) => (
            <Button key={r} variant={r === days ? "primary" : "secondary"} className="min-h-9 px-3"
              aria-pressed={r === days} onClick={() => setDays(r)}>
              {r} days
            </Button>
          ))}
        </div>
      </div>
      <BillingAlert error={error} />
      {data && <Dashboard data={data} onChanged={() => load(days)} onError={setError} />}
    </div>
  );
}

function Dashboard({ data, onChanged, onError }: {
  data: AdminOverview;
  onChanged: () => void;
  onError: (e: unknown) => void;
}) {
  const paid = (data.payment_counts.paid ?? 0) + (data.payment_counts.partially_refunded ?? 0)
    + (data.payment_counts.refunded ?? 0) + (data.payment_counts.disputed ?? 0);
  return (
    <>
      {data.alerts.length > 0 && (
        <div className="space-y-2" aria-label="Alerts">
          {data.alerts.map((a) => (
            <Alert key={a.kind} tone={a.severity === "critical" ? "bad" : "warn"} role="alert"
              title={a.severity === "critical" ? "Critical" : "Warning"}>{a.message}</Alert>
          ))}
        </div>
      )}

      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Payments completed" value={String(paid)}
          note={`${data.payment_counts.refunded ?? 0} refunded · ${data.payment_counts.disputed ?? 0} disputed · ${data.payment_counts.failed ?? 0} failed`} />
        <Stat label="Credits sold / consumed" value={`${data.credits.sold} / ${data.credits.consumed}`}
          note={`${data.credits.reversed} reversed · ${data.credits.outstanding} unspent across all users`} />
        <Stat label="LLM spend" value={dollars(data.llm.total_cost_usd)}
          note={`${data.llm.calls} calls${data.llm.unpriced_calls ? ` · ${data.llm.unpriced_calls} unpriced` : ""}`} />
        <Stat label="LLM cost per analysis" value={dollars(data.llm.avg_cost_per_analysis_usd, 3)}
          note={`${data.llm.analyses} analyses`} />
      </dl>

      <Card>
        <h2 className="text-lg font-semibold">Margin by plan</h2>
        <p className="mt-1 text-xs text-muted">
          Settled revenue excludes tax collected by Dodo. {data.fees_are_estimates
            ? "Dodo fees are estimates from billing.toml; check them against Dodo's payout reports."
            : "Settlement is already net of Dodo fees."}{" "}
          &quot;If fully used&quot; assumes every credit or pass run is used, at the average LLM cost per analysis.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="py-2 pr-3 font-medium">Plan</th>
                <th className="py-2 pr-3 text-right font-medium">Sold</th>
                <th className="py-2 pr-3 text-right font-medium">Settled</th>
                <th className="py-2 pr-3 text-right font-medium">Refunded</th>
                <th className="py-2 pr-3 text-right font-medium">Dodo fees</th>
                <th className="py-2 pr-3 text-right font-medium">Net</th>
                <th className="py-2 pr-3 text-right font-medium">LLM if fully used</th>
                <th className="py-2 text-right font-medium">Margin if fully used</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border tabular-nums">
              {data.margin.length === 0 && (
                <tr><td colSpan={8} className="py-3 text-muted">No paid purchases in this period.</td></tr>
              )}
              {data.margin.map((m) => (
                <tr key={m.product_key}>
                  <td className="py-2 pr-3">{m.product_key}
                    {m.other_currency_units > 0 && <span className="block text-xs text-muted">{m.other_currency_units} settled in another currency, not included</span>}
                  </td>
                  <td className="py-2 pr-3 text-right">{m.units}</td>
                  <td className="py-2 pr-3 text-right">{usd(m.settled_usd_cents)}</td>
                  <td className="py-2 pr-3 text-right">{usd(m.refunded_usd_cents)}</td>
                  <td className="py-2 pr-3 text-right">{usd(m.fees_usd_cents)}</td>
                  <td className="py-2 pr-3 text-right font-medium">{usd(m.net_usd_cents)}</td>
                  <td className="py-2 pr-3 text-right">{usd(m.llm_cost_if_fully_used_usd_cents)}</td>
                  <td className="py-2 text-right font-medium">{usd(m.margin_if_fully_used_usd_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Reviews data={data} onChanged={onChanged} onError={onError} />

      {data.failing_webhooks.length > 0 && (
        <Card>
          <h2 className="text-lg font-semibold">Webhooks not yet processed</h2>
          <p className="mt-1 text-xs text-muted">Dodo retries for about a day; you can also replay from Dodo&apos;s webhook logs.</p>
          <ul className="mt-3 divide-y divide-border text-sm">
            {data.failing_webhooks.map((w) => (
              <li key={w.event_id} className="py-2">
                <span className="font-medium">{w.event_type}</span> <code className="text-xs">{w.event_id}</code>
                <span className="block text-xs text-muted">{w.failures} failures · {w.last_error ?? "unknown error"} · first seen {when(w.received_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <h2 className="text-lg font-semibold">LLM spend by model</h2>
          <SimpleTable rows={data.llm.by_model.map((m) => [m.model, String(m.calls), dollars(m.cost_usd)])}
            head={["Model", "Calls", "Cost"]} empty="No Claude calls in this period." />
        </Card>
        <Card>
          <h2 className="text-lg font-semibold">LLM spend by day (UTC)</h2>
          <SimpleTable rows={data.llm.daily.map((d) => [d.day, dollars(d.cost_usd)])}
            head={["Day", "Cost"]} empty="No Claude calls in this period." />
        </Card>
      </div>

      <Card>
        <h2 className="text-lg font-semibold">Recent payments</h2>
        <SimpleTable head={["When", "Buyer", "Plan", "Status", "Amount", "Dodo payment"]} empty="No payments in this period."
          rows={data.payments.map((p) => [
            when(p.created_at), p.email ?? "deleted account", p.product_key, p.status,
            p.amount_minor !== null && p.currency
              ? `${formatMoney(p.amount_minor, p.currency)}${p.refunded_amount_minor ? ` (refunded ${formatMoney(p.refunded_amount_minor, p.currency)})` : ""}`
              : "n/a",
            p.provider_payment_id ?? "n/a",
          ])} />
      </Card>
    </>
  );
}

function Reviews({ data, onChanged, onError }: {
  data: AdminOverview;
  onChanged: () => void;
  onError: (e: unknown) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  return (
    <Card>
      <h2 className="text-lg font-semibold">Needs review</h2>
      {data.reviews.length === 0 ? (
        <p className="mt-2 text-sm text-muted">Nothing to review.</p>
      ) : (
        <ul className="mt-3 divide-y divide-border text-sm">
          {data.reviews.map((r) => (
            <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="font-medium">{REVIEW_LABEL[r.kind] ?? r.kind}</p>
                <p className="break-all text-xs text-muted">
                  {when(r.created_at)}{r.payment_id ? ` · payment ${r.payment_id}` : ""} · {JSON.stringify(r.detail)}
                </p>
              </div>
              <Button variant="secondary" className="min-h-9 px-3" busy={busy === r.id} onClick={async () => {
                setBusy(r.id);
                try {
                  await adminBillingApi.resolveReview(r.id);
                  onChanged();
                } catch (e) {
                  onError(e);
                } finally {
                  setBusy(null);
                }
              }}>
                Mark resolved
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <Card as="div">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd>
      {note && <dd className="mt-1 text-xs text-muted">{note}</dd>}
    </Card>
  );
}

function SimpleTable({ head, rows, empty }: { head: string[]; rows: string[][]; empty: string }) {
  if (rows.length === 0) return <p className="mt-2 text-sm text-muted">{empty}</p>;
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted">
          <tr>{head.map((h) => <th key={h} className="py-2 pr-3 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-border tabular-nums">
          {rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="py-2 pr-3">{c}</td>)}</tr>)}
        </tbody>
      </table>
    </div>
  );
}
