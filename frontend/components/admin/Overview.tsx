"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { BarList, PeriodBars, PeriodLines, StatTile, count, pct, usd } from "@/components/admin/charts";
import { when } from "@/components/admin/ui";
import { ErrorState, Skeleton } from "@/components/app/states";
import { Button, Card } from "@/components/ui";
import { adminApi, adminError } from "@/lib/adminApi";
import type { AdminHome } from "@/lib/schemas";

const RANGES = [7, 30, 90] as const;
const n = (v: number) => v.toLocaleString("en");

/** KPI tiles, signups and money over time, and the funnel. Money tiles only for roles that see money. */
export function Overview() {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<AdminHome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    adminApi.home(days).then(setData).catch((e) => setError(adminError(e)));
  }, [days]);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Date range" className="flex gap-1">
          {RANGES.map((r) => (
            <Button key={r} variant={r === days ? "primary" : "secondary"} className="min-h-9 px-3" aria-pressed={r === days}
              onClick={() => setDays(r)}>{r} days</Button>
          ))}
        </div>
        <a href={adminApi.homeCsvUrl(days)} className="text-sm font-medium text-accent underline">Export daily CSV</a>
      </div>
      {error && <ErrorState message={error} onRetry={load} />}
      {!data && !error && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><p role="status" className="sr-only">Loading</p>
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}</div>
      )}
      {data && <Dashboard data={data} />}
    </div>
  );
}

function Dashboard({ data }: { data: AdminHome }) {
  const u = data.users;
  const r = data.revenue;
  const c = data.costs;
  const f = data.funnel;
  const steps: [string, number][] = [["Landing views", f.landing_views], ["Signed up", f.signups],
    ["First tailoring", f.first_tailoring], ["Downloaded", f.downloaded], ["Paid", f.paid]];
  const moneySeries = [
    ...(r ? [{ key: "revenue_usd", label: "Revenue", color: "series-1" as const }] : []),
    ...(c ? [{ key: "cost_usd", label: "Claude cost", color: "series-2" as const }] : []),
  ];
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Users" value={n(u.total)} sub={`+${n(u.new_7d)} in 7 days · +${n(u.new_30d)} in 30`} />
        <StatTile label="Active (day / week / month)" value={`${n(u.dau)} / ${n(u.wau)} / ${n(u.mau)}`} />
        <StatTile label="Tailorings" value={n(data.tailorings.d30)} sub={`${n(data.tailorings.d7)} in the last 7 days · 30-day total`} />
        <StatTile label="Waitlist" value={n(u.waitlist)} sub={<Link href="/admin/invites?tab=waitlist" className="underline">Work the waitlist</Link>} />
        <StatTile label="Paid users" value={n(u.paid)} sub="Paid at least once" />
        <StatTile label="Open tickets" value={n(data.open_tickets)} sub={<Link href="/admin/support" className="underline">Support inbox</Link>} />
        {r && <StatTile label="Revenue (30 days)" value={usd(r.revenue_30d_usd)}
          sub={`MRR-equivalent ${usd(r.mrr_equivalent_usd)} · ${r.active_pro} on Pro`} />}
        {r && <StatTile label="Credits sold / used (30 days)" value={`${n(r.credits_sold_30d)} / ${n(r.credits_consumed_30d)}`} />}
        {c && <StatTile label="Claude cost (30 days)" value={usd(c.llm_cost_30d_usd)}
          sub={c.gross_margin !== undefined ? `Gross margin ${pct(c.gross_margin)}` : undefined} />}
      </div>
      {data.as_of ? <p className="text-xs text-muted">Money figures as of {when(data.as_of)}; users and activity are live.</p>
        : (r || c) && <p className="text-xs text-muted">Money figures appear once the rollup job has run (docs/billing.md §12).</p>}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-3 text-lg font-semibold">Sign-ups by day</h2>
          <PeriodBars title="Sign-ups by day" data={data.series} x="day" format={count} axisFormat={count}
            series={{ key: "signups", label: "Sign-ups", color: "series-1" }} />
        </Card>
        {moneySeries.length > 0 && (
          <Card>
            <h2 className="mb-3 text-lg font-semibold">{moneySeries.length === 2 ? "Revenue and Claude cost by day" : `${moneySeries[0].label} by day`}</h2>
            <PeriodLines title="Revenue and Claude cost by day" data={data.series} x="day" series={moneySeries} />
          </Card>
        )}
      </div>
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Funnel</h2>
        <p className="mb-3 text-sm text-muted">People who signed up in this range, and how far they got. Landing views are a cookie-free daily count.</p>
        <BarList label="Funnel" format={count} rows={steps.map(([label, value], i) => ({
          key: label, value, sub: i > 0 && steps[i - 1][1] > 0 ? `· ${pct(value / steps[i - 1][1])} of the step before` : undefined }))} />
      </Card>
    </>
  );
}
