"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { BarList, PeriodLines, StatTile, pct, usd } from "@/components/admin/charts";
import { DataTable, Pager, Pill, ReasonDialog, when, type Column } from "@/components/admin/ui";
import { ErrorState, PageHeader } from "@/components/app/states";
import { Alert, Button, Card, Label, inlineInputClass, inputClass } from "@/components/ui";
import { adminApi, adminError, attempt } from "@/lib/adminApi";
import { api } from "@/lib/api";
import { formatMoney } from "@/lib/billing";
import { can } from "@/lib/roles";
import type { AdminPaymentRow, AdminRevenue, Me } from "@/lib/schemas";

const RANGES = [7, 30, 90, 365] as const;
const STATUSES = ["paid", "partially_refunded", "refunded", "disputed", "pending", "failed"] as const;
const money = (minor: number | null, currency: string | null) => (minor === null || !currency ? "—" : formatMoney(minor, currency));
const digitsOf = (currency: string) =>
  new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions().maximumFractionDigits ?? 2;

/** Revenue: totals, trend, by product and currency, subscriptions, and the payments list with refunds. */
export default function AdminRevenuePage() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<AdminRevenue | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.me().then(setMe).catch(() => setMe(null)); }, []);
  const load = useCallback(() => {
    setError(null);
    adminApi.revenue(days).then(setData).catch((e) => setError(adminError(e)));
  }, [days]);
  useEffect(() => { if (can(me, "billing.read")) load(); }, [me, load]);

  if (me === undefined) return null;
  if (!can(me, "billing.read")) return <Alert tone="info" title="Not available for your role">Revenue needs an admin.</Alert>;

  return (
    <div className="space-y-6">
      <PageHeader title="Revenue" intro="Settled amounts in USD, excluding tax. Refunds and disputes come from Dodo's webhooks."
        actions={
          <div role="group" aria-label="Date range" className="flex gap-1">
            {RANGES.map((r) => (
              <Button key={r} variant={r === days ? "primary" : "secondary"} className="min-h-9 px-3" aria-pressed={r === days}
                onClick={() => setDays(r)}>{r === 365 ? "1 year" : `${r} days`}</Button>
            ))}
          </div>
        } />
      {error && <ErrorState message={error} onRetry={load} />}
      {data && <Summary data={data} />}
      <Payments canRefund={can(me, "billing.write")} onRefunded={load} />
    </div>
  );
}

function AsOf({ at }: { at: string | null }) {
  return at ? <p className="text-xs text-muted">Totals as of {when(at)}. The rollup refreshes every 15 minutes.</p> : (
    <Alert tone="warn" title="No rollup yet">
      Totals come from a scheduled job that hasn&apos;t run. Run <code>python -m app.billing.cli refresh-aggregates --days 400</code> once, then add the cron line from docs/billing.md.
    </Alert>
  );
}

function Summary({ data }: { data: AdminRevenue }) {
  const t = data.totals;
  const s = data.subscriptions;
  const r = data.referral_liability;
  return (
    <>
      <AsOf at={data.as_of} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Gross" value={usd(t.gross_usd)} sub={`${t.payments} payments`} />
        <StatTile label="Refunds" value={usd(t.refunds_usd)} sub={`${t.disputes} disputed`} />
        <StatTile label={data.fees_are_estimates ? "Fees (estimated)" : "Fees"} value={usd(t.fees_usd)} />
        <StatTile label="Net after fees" value={usd(t.net_after_fees_usd)} sub={`Net of refunds ${usd(t.net_usd)}`} />
      </div>
      {t.unsettled > 0 && (
        <Alert tone="info" title={`${t.unsettled} payment${t.unsettled === 1 ? "" : "s"} not settled in USD yet`}>
          They count in payments and in the currency table, but not in the USD totals until Dodo reports the settlement.
        </Alert>
      )}
      <Card>
        <h2 className="mb-3 text-lg font-semibold">Revenue by day</h2>
        {data.daily.length === 0 ? <p className="text-sm text-muted">No payments in this range.</p> : (
          <PeriodLines title="Revenue by day" data={data.daily} x="day" series={[
            { key: "gross_usd", label: "Gross", color: "series-1" }, { key: "net_usd", label: "Net after fees", color: "series-2" }]} />
        )}
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 text-lg font-semibold">By product</h2>
          <BarList label="Gross by product" rows={data.by_product.map((p) => ({ key: p.product_key, value: p.gross_usd,
            sub: `· ${p.payments} paid · net ${usd(p.net_usd)}` }))} />
        </Card>
        <Card>
          <h2 className="mb-3 text-lg font-semibold">By currency</h2>
          {data.by_currency.length === 0 ? <p className="text-sm text-muted">Nothing in this range.</p> : (
            <table className="w-full text-left text-sm" aria-label="By currency">
              <thead className="text-xs text-muted"><tr>
                <th scope="col" className="py-1 font-medium">Currency</th><th scope="col" className="py-1 text-right font-medium">Payments</th>
                <th scope="col" className="py-1 text-right font-medium">Charged (incl. tax)</th><th scope="col" className="py-1 text-right font-medium">Refunded</th>
              </tr></thead>
              <tbody className="divide-y divide-border">
                {data.by_currency.map((c) => (
                  <tr key={c.currency}>
                    <td className="py-1.5">{c.currency}</td><td className="py-1.5 text-right tabular-nums">{c.payments}</td>
                    <td className="py-1.5 text-right tabular-nums">{c.currency === "?" ? "—" : formatMoney(c.gross_minor, c.currency)}</td>
                    <td className="py-1.5 text-right tabular-nums">{c.currency === "?" ? "—" : formatMoney(c.refunded_minor, c.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card>
          <h2 className="mb-3 text-lg font-semibold">Subscriptions</h2>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-muted">Active</dt><dd className="text-xl font-semibold tabular-nums">{s.active}</dd></div>
            <div><dt className="text-muted">Renewing in 7 days</dt><dd className="text-xl font-semibold tabular-nums">{s.renewals_due_7d}</dd></div>
            <div><dt className="text-muted">Cancelled in range</dt><dd className="text-xl font-semibold tabular-nums">{s.cancelled_in_window}</dd></div>
            <div><dt className="text-muted">Churn in range</dt><dd className="text-xl font-semibold tabular-nums">{pct(s.churn_rate)}</dd></div>
          </dl>
        </Card>
        <Card>
          <h2 className="mb-1 text-lg font-semibold">Referral liability</h2>
          <p className="mb-3 text-sm text-muted">Credits given as referral rewards, valued at the credit pack&apos;s USD price ({usd(r.per_credit_usd)} a credit).</p>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-muted">Granted in range</dt><dd className="text-xl font-semibold tabular-nums">{r.credits_granted_in_window}</dd></div>
            <div><dt className="text-muted">Estimated value</dt><dd className="text-xl font-semibold tabular-nums">{usd(r.est_value_usd)}</dd></div>
            <div><dt className="text-muted">Granted all time</dt><dd className="text-xl font-semibold tabular-nums">{r.credits_granted_total}</dd></div>
          </dl>
        </Card>
      </div>
    </>
  );
}

function Payments({ canRefund, onRefunded }: { canRefund: boolean; onRefunded: () => void }) {
  const search = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const status = search.get("status") ?? "";
  const q = search.get("q") ?? "";
  const page = Number(search.get("page") ?? 1) || 1;
  const [rows, setRows] = useState<{ items: AdminPaymentRow[]; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState(q);
  const [refunding, setRefunding] = useState<AdminPaymentRow | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    adminApi.payments({ status, q, page }).then((r) => setRows({ items: r.items, total: r.total }))
      .catch((e) => setError(adminError(e)));
  }, [status, q, page]);
  useEffect(() => { load(); }, [load]);

  const go = (next: Record<string, string | number | undefined>) => {
    const p = new URLSearchParams(search.toString());
    for (const [k, v] of Object.entries(next)) if (v === undefined || v === "") p.delete(k); else p.set(k, String(v));
    if (!("page" in next)) p.delete("page");
    router.replace(`${path}${p.size ? `?${p}` : ""}`, { scroll: false });
  };

  const columns: Column<AdminPaymentRow>[] = [
    { key: "paid_at", label: "Date", render: (p) => when(p.paid_at ?? p.created_at) },
    { key: "user", label: "Customer", render: (p) => p.user_id
      ? <Link href={`/admin/users/${p.user_id}`} className="text-accent underline">{p.user_email ?? "account"}</Link>
      : <span className="text-muted">deleted account</span> },
    { key: "product", label: "Product", render: (p) => <>{p.product_key}{p.mode === "test" && <span className="ml-1"><Pill>test</Pill></span>}</> },
    { key: "amount", label: "Amount", className: "text-right tabular-nums", render: (p) => (
      <>{money(p.amount_minor, p.currency)}{p.refunded_amount_minor > 0 && (
        <span className="block text-xs text-muted">−{money(p.refunded_amount_minor, p.currency)} refunded</span>)}</>) },
    { key: "status", label: "Status", render: (p) => (
      <span className="flex flex-wrap gap-1">
        <Pill tone={p.status === "paid" ? "ok" : p.status === "failed" || p.status === "disputed" ? "bad" : p.status.includes("refund") ? "warn" : "neutral"}>
          {p.status.replaceAll("_", " ")}
        </Pill>
        {p.disputed && <Pill tone="bad">dispute</Pill>}
      </span>) },
    ...(canRefund ? [{ key: "actions", label: "", className: "text-right", render: (p: AdminPaymentRow) =>
      (p.status === "paid" || p.status === "partially_refunded") && p.provider_payment_id ? (
        <Button variant="secondary" className="min-h-8 px-2 text-xs" onClick={() => { setNotice(null); setRefunding(p); }}
          aria-label={`Refund ${p.user_email ?? "payment"} ${money(p.amount_minor, p.currency)}`}>Refund</Button>) : null }] : []),
  ];

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Payments</h2>
        <p className="text-sm text-muted">Every checkout, newest first. Disputes are answered in Dodo&apos;s dashboard.</p>
      </div>
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); go({ q: query.trim() }); }}>
        <div>
          <Label htmlFor="pay-q">Email or Dodo payment ID</Label>
          <input id="pay-q" className={inlineInputClass} value={query} onChange={(e) => setQuery(e.target.value)} maxLength={200} />
        </div>
        <div>
          <Label htmlFor="pay-status">Status</Label>
          <select id="pay-status" className={inlineInputClass} value={status} onChange={(e) => go({ status: e.target.value })}>
            <option value="">Any</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s.replaceAll("_", " ")}</option>)}
          </select>
        </div>
        <Button type="submit" variant="secondary" className="min-h-10">Search</Button>
      </form>
      {notice && <p role="status" className="rounded-lg bg-ok-bg px-3 py-2 text-sm text-ok">{notice}</p>}
      {error ? <ErrorState message={error} onRetry={load} /> : (
        <>
          <DataTable label="Payments" columns={columns} rows={rows?.items ?? null} empty="No payments match." />
          {rows && rows.total > 0 && <Pager page={page} pageSize={25} total={rows.total} onPage={(p) => go({ page: p })} />}
        </>
      )}
      {refunding && <RefundDialog payment={refunding} onClose={() => setRefunding(null)}
        onDone={(text) => { setNotice(text); load(); onRefunded(); }} />}
    </Card>
  );
}

function RefundDialog({ payment, onClose, onDone }: { payment: AdminPaymentRow; onClose: () => void; onDone: (notice: string) => void }) {
  const currency = payment.currency ?? "USD";
  const digits = digitsOf(currency);
  const left = (payment.amount_minor ?? 0) - payment.refunded_amount_minor;
  const [amount, setAmount] = useState("");
  const minor = amount.trim() === "" ? undefined : Math.round(Number(amount) * 10 ** digits);
  const valid = minor === undefined || (Number.isFinite(minor) && minor >= 1 && minor <= left);
  return (
    <ReasonDialog title="Refund payment" confirm={minor && minor < left ? "Refund part" : "Refund in full"} danger valid={valid}
      description={<>Asks Dodo to refund {payment.user_email ?? "this customer"}. Up to {money(left, currency)} is left to refund.
        Credits come back off the account per the refund policy once Dodo confirms.</>}
      extra={
        <div>
          <Label htmlFor="refund-amount" hint={`(${currency}; leave empty for the full ${money(left, currency)})`}>Amount</Label>
          <input id="refund-amount" type="number" inputMode="decimal" min={0} step={1 / 10 ** digits} className={inputClass}
            value={amount} onChange={(e) => setAmount(e.target.value)} aria-invalid={!valid} />
          {!valid && <p className="mt-1 text-xs text-bad">Enter an amount up to {money(left, currency)}.</p>}
        </div>
      }
      onClose={onClose}
      onConfirm={async (reason) => {
        const r = await attempt(() => adminApi.refund(payment.id, reason, minor && minor < left ? minor : undefined));
        onDone(`Refund requested${r.status ? ` (${r.status})` : ""}. The payment updates when Dodo confirms.`);
      }} />
  );
}
