"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { BarList, BudgetMeter, PeriodBars, StatTile, pct, usd } from "@/components/admin/charts";
import { Pill, ReasonDialog, when } from "@/components/admin/ui";
import { ErrorState, PageHeader } from "@/components/app/states";
import { Alert, Button, Card, Label, inputClass } from "@/components/ui";
import { adminApi, adminError, attempt } from "@/lib/adminApi";
import { api } from "@/lib/api";
import { can } from "@/lib/roles";
import type { AdminCosts, Me, SettingKey } from "@/lib/schemas";

const RANGES = [7, 30, 90, 365] as const;
const GRAINS = ["day", "week", "month"] as const;
const STEPS: Record<string, string> = {
  gap_analysis: "Gap analysis", tailor: "Tailoring", tailor_repair: "Tailoring repair", ats_semantic: "ATS semantic match",
  mentor: "Mentor questions",
};
const PLANS: Record<string, string> = { free: "Free tier", pass: "Pass", pro: "Pro", credit: "Credits", none: "Not tied to an analysis" };
const PAUSED: Record<string, string> = {
  manual: "Paused by hand", daily_budget: "Paused: daily budget reached", monthly_budget: "Paused: monthly budget reached",
};
/** Per-analysis amounts: sub-dollar values to 4 places, where the differences are. */
const cents = (v: number | null) => usd(v, v !== null && Math.abs(v) < 1 ? 4 : 2);

/** Claude spend: budgets and the kill switch first, then the trend and where the money goes. */
export default function AdminCostsPage() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [days, setDays] = useState<number>(30);
  const [grain, setGrain] = useState<(typeof GRAINS)[number]>("day");
  const [data, setData] = useState<AdminCosts | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.me().then(setMe).catch(() => setMe(null)); }, []);
  const load = useCallback(() => {
    setError(null);
    adminApi.costs(days, grain).then(setData).catch((e) => setError(adminError(e)));
  }, [days, grain]);
  useEffect(() => { if (can(me, "costs.read")) load(); }, [me, load]);

  if (me === undefined) return null;
  if (!can(me, "costs.read")) return <Alert tone="info" title="Not available for your role">Costs need an admin.</Alert>;

  return (
    <div className="space-y-6">
      <PageHeader title="Costs" intro="What Claude costs us, at the prices in billing.toml, and how close we are to the budget."
        actions={
          <div role="group" aria-label="Date range" className="flex gap-1">
            {RANGES.map((r) => (
              <Button key={r} variant={r === days ? "primary" : "secondary"} className="min-h-9 px-3" aria-pressed={r === days}
                onClick={() => setDays(r)}>{r === 365 ? "1 year" : `${r} days`}</Button>
            ))}
          </div>
        } />
      {error && <ErrorState message={error} onRetry={load} />}
      {data && (
        <>
          <Budget data={data} canEdit={can(me, "settings.write")} onChanged={load} />
          {data.as_of ? <p className="text-xs text-muted">Breakdowns as of {when(data.as_of)}; budget spend is live.</p> : (
            <Alert tone="warn" title="No rollup yet">
              Breakdowns come from a scheduled job that hasn&apos;t run. Run <code>python -m app.billing.cli refresh-aggregates --days 400</code> once, then add the cron line from docs/billing.md.
            </Alert>
          )}
          {data.unpriced_calls > 0 && (
            <Alert tone="warn" title={`${data.unpriced_calls} call${data.unpriced_calls === 1 ? "" : "s"} with no price`}>
              A model in use has no row in billing.toml [llm_prices], so those calls count as $0 here. Add its prices.
            </Alert>
          )}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Spend" value={usd(data.total_usd)} sub={`${data.calls.toLocaleString("en")} calls`} />
            <StatTile label="Per analysis" value={cents(data.per_analysis.avg_usd)} sub={`p95 ${cents(data.per_analysis.p95_usd)}`} />
            <StatTile label="Free-tier burn" value={usd(data.free_tier_usd)} sub="Claude spend on free analyses" />
            <StatTile label="Failed calls" value={pct(data.error_rate)} sub={`${usd(data.wasted_usd)} spent on unusable answers`} />
          </div>
          <Card>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-semibold">Spend by {grain}</h2>
              <div role="group" aria-label="Group by" className="flex rounded-lg border border-border p-0.5">
                {GRAINS.map((g) => (
                  <button key={g} type="button" aria-pressed={grain === g} onClick={() => setGrain(g)}
                    className={`rounded-md px-3 py-1 text-sm ${grain === g ? "bg-surface-2 font-medium text-fg" : "text-muted"}`}>
                    {g[0].toUpperCase() + g.slice(1)}
                  </button>
                ))}
              </div>
            </div>
            {data.series.length === 0 ? <p className="text-sm text-muted">No Claude calls in this range.</p> : (
              <PeriodBars title={`Spend by ${grain}`} data={data.series} x="period" series={{ key: "cost_usd", label: "Spend", color: "series-1" }} />
            )}
          </Card>
          <div className="grid gap-6 lg:grid-cols-3">
            {([["By pipeline step", data.by_step, STEPS], ["By model", data.by_model, {}], ["By plan", data.by_plan, PLANS]] as const).map(([title, rows, names]) => (
              <Card key={title}>
                <h2 className="mb-3 text-lg font-semibold">{title}</h2>
                <BarList label={title} names={names} rows={rows.map((r) => ({ key: r.key, value: r.cost_usd, sub: `· ${r.calls.toLocaleString("en")}` }))} />
              </Card>
            ))}
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <Margin data={data} />
            <Card>
              <h2 className="mb-3 text-lg font-semibold">Top users by spend</h2>
              {data.top_users.length === 0 ? <p className="text-sm text-muted">Nobody in this range.</p> : (
                <ol className="divide-y divide-border text-sm" aria-label="Top users by spend">
                  {data.top_users.map((u) => (
                    <li key={u.user_id} className="flex items-baseline justify-between gap-3 py-1.5">
                      <Link href={`/admin/users/${u.user_id}`} className="truncate text-accent underline">{u.email}</Link>
                      <span className="shrink-0 tabular-nums">{usd(u.cost_usd)} <span className="text-xs text-muted">· {u.calls} calls</span></span>
                    </li>
                  ))}
                </ol>
              )}
            </Card>
          </div>
          <Prices data={data} />
        </>
      )}
    </div>
  );
}

function Margin({ data }: { data: AdminCosts }) {
  const m = data.margin;
  const unit = m.revenue_per_analysis_usd !== null && m.cost_per_analysis_usd !== null
    ? m.revenue_per_analysis_usd - m.cost_per_analysis_usd : null;
  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Margin</h2>
      <p className="mb-3 text-sm text-muted">Net revenue after refunds and fees against Claude spend, over {m.analyses.toLocaleString("en")} analyses.</p>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div><dt className="text-muted">Net revenue</dt><dd className="text-xl font-semibold tabular-nums">{usd(m.net_revenue_usd)}</dd></div>
        <div><dt className="text-muted">Claude spend</dt><dd className="text-xl font-semibold tabular-nums">{usd(m.cost_usd)}</dd></div>
        <div><dt className="text-muted">Revenue per analysis</dt><dd className="text-xl font-semibold tabular-nums">{cents(m.revenue_per_analysis_usd)}</dd></div>
        <div><dt className="text-muted">Cost per analysis</dt><dd className="text-xl font-semibold tabular-nums">{cents(m.cost_per_analysis_usd)}</dd></div>
        <div className="col-span-2"><dt className="text-muted">Left per analysis</dt>
          <dd className="text-xl font-semibold tabular-nums">{cents(unit)}</dd></div>
      </dl>
    </Card>
  );
}

function Prices({ data }: { data: AdminCosts }) {
  const caps = data.per_user_daily_caps;
  return (
    <Card>
      <h2 className="mb-1 text-lg font-semibold">Prices and per-user caps</h2>
      <p className="mb-3 text-sm text-muted">
        From billing.toml (change there and redeploy). Each account gets {caps.free ?? "—"} Claude analyses a day on the free tier
        and {caps.paid ?? "—"} when paying; past that, analyses run without Claude.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[28rem] text-left text-sm" aria-label="Model prices">
          <thead className="text-xs text-muted"><tr>
            <th scope="col" className="py-1 font-medium">Model</th>
            {["Input", "Output", "Cache read", "Cache write"].map((h) => <th key={h} scope="col" className="py-1 text-right font-medium">{h}</th>)}
          </tr></thead>
          <tbody className="divide-y divide-border">
            {data.prices.map((p) => (
              <tr key={p.model}>
                <td className="py-1.5 font-mono text-xs">{p.model}</td>
                {[p.input, p.output, p.cache_read, p.cache_write].map((v, i) => (
                  <td key={i} className="py-1.5 text-right tabular-nums">{v === null ? "—" : `$${v}`}</td>))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-xs text-muted">USD per million tokens.</p>
      </div>
    </Card>
  );
}

type Pending = { key: SettingKey; value: number | boolean; label: string };

/** Today and this month against the budgets; the kill switch and the manual pause. */
function Budget({ data, canEdit, onChanged }: { data: AdminCosts; canEdit: boolean; onChanged: () => void }) {
  const b = data.budget;
  const [daily, setDaily] = useState(String(b.daily_budget_usd));
  const [monthly, setMonthly] = useState(String(b.monthly_budget_usd));
  const [pending, setPending] = useState<Pending | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => { setDaily(String(b.daily_budget_usd)); setMonthly(String(b.monthly_budget_usd)); }, [b.daily_budget_usd, b.monthly_budget_usd]);
  const amount = (s: string) => { const n = Number(s); return s.trim() !== "" && Number.isFinite(n) && n > 0 ? n : null; };

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Budget</h2>
          <p className="text-sm text-muted">
            {b.kill_switch ? "Kill switch on: past a budget, new analyses pause until the next UTC day or month, or until the budget is raised."
              : "Kill switch off: budgets only send alerts (50%, 80%, 100%) to admins and Slack."}
          </p>
        </div>
        {b.paused ? <Pill tone="bad">{PAUSED[b.paused]}</Pill> : <Pill tone="ok">Analyses running</Pill>}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <BudgetMeter label="Today (UTC)" spent={b.today_usd} budget={b.daily_budget_usd} />
        <BudgetMeter label="This month (UTC)" spent={b.month_usd} budget={b.monthly_budget_usd} />
      </div>
      {notice && <p role="status" className="rounded-lg bg-ok-bg px-3 py-2 text-sm text-ok">{notice}</p>}
      {canEdit ? (
        <div className="grid gap-4 border-t border-border pt-4 sm:grid-cols-2">
          {([["daily_budget_usd", "Daily budget", daily, setDaily, b.daily_budget_usd],
            ["monthly_budget_usd", "Monthly budget", monthly, setMonthly, b.monthly_budget_usd]] as const).map(([key, label, draft, set, current]) => (
            <div key={key}>
              <Label htmlFor={key} hint="(USD)">{label}</Label>
              <div className="flex gap-2">
                <input id={key} type="number" min={1} step="any" className={inputClass} value={draft} onChange={(e) => set(e.target.value)} />
                <Button variant="secondary" disabled={amount(draft) === null || amount(draft) === current}
                  onClick={() => setPending({ key, value: amount(draft)!, label: `${label} → ${usd(amount(draft))}` })}>Save</Button>
              </div>
            </div>
          ))}
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <Button variant="secondary" onClick={() => setPending({ key: "budget_kill_switch", value: !b.kill_switch,
              label: b.kill_switch ? "Turn the kill switch off (alerts only)" : "Turn the kill switch on" })}>
              {b.kill_switch ? "Turn kill switch off" : "Turn kill switch on"}
            </Button>
            <Button variant={b.analyses_paused ? "primary" : "danger"} onClick={() => setPending({ key: "analyses_paused",
              value: !b.analyses_paused, label: b.analyses_paused ? "Resume new analyses" : "Pause all new analyses now" })}>
              {b.analyses_paused ? "Resume analyses" : "Pause analyses now"}
            </Button>
          </div>
        </div>
      ) : <p className="text-xs text-muted">Changing budgets or the kill switch needs a superadmin.</p>}
      {pending && <ReasonDialog title="Change the budget" confirm="Change" danger={pending.key === "analyses_paused" && pending.value === true}
        description={pending.label} onClose={() => setPending(null)}
        onConfirm={async (reason) => {
          await attempt(() => adminApi.setSetting(pending.key, pending.value, reason));
          setNotice(`Saved: ${pending.label}.`);
          onChanged();
        }} />}
    </Card>
  );
}
