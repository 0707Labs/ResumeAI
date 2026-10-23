"use client";

/**
 * Charts for the admin money pages. Colors come from the --series-* tokens (validated
 * for colour-blind separation on both themes); text stays in the text tokens. Every
 * chart has a hover tooltip and a table view, so nothing depends on colour or a mouse.
 */
import { Bar, BarChart, CartesianGrid, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export const usd = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? "—" : `$${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);
/** A period label: "2026-10-20" (day or week start) or "2026-10" (month), read as UTC. */
export function period(p: string): string {
  const [y, m, d] = p.split("-").map(Number);
  const date = new Date(Date.UTC(y, (m ?? 1) - 1, d ?? 1));
  return date.toLocaleDateString("en", d ? { day: "numeric", month: "short", timeZone: "UTC" } : { month: "short", year: "numeric", timeZone: "UTC" });
}

export function StatTile({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <p className="text-xs font-medium text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-fg">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
    </div>
  );
}

export interface Series { key: string; label: string; color: "series-1" | "series-2" }

/** Axis money: whole dollars from $10 up, cents below (so small spend doesn't read "$0, $0, $0"). */
export const count = (v: unknown) => Number(v).toLocaleString("en");
const tick = (v: unknown) => { const n = Number(v); return usd(n, n !== 0 && Math.abs(n) < 10 ? 2 : 0); };
const axis = { stroke: "var(--border-strong)", tick: { fill: "var(--muted)", fontSize: 12 }, tickLine: false } as const;

function ChartTooltip({ active, payload, label, series, format }: {
  active?: boolean; payload?: { dataKey?: unknown; value?: unknown }[]; label?: unknown; series: Series[]; format: (v: number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium text-fg">{period(String(label))}</p>
      {series.map((s) => {
        const item = payload.find((p) => p.dataKey === s.key);
        return item ? (
          <p key={s.key} className="flex items-center gap-2 text-fg">
            <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ background: `var(--${s.color})` }} />
            <span className="text-muted">{s.label}</span><span className="ml-auto tabular-nums">{format(Number(item.value))}</span>
          </p>
        ) : null;
      })}
    </div>
  );
}

function Legend({ series }: { series: Series[] }) {
  if (series.length < 2) return null;
  return (
    <ul className="mb-2 flex flex-wrap gap-4 text-xs text-muted" aria-label="Legend">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-0.5 w-4 rounded" style={{ background: `var(--${s.color})` }} />{s.label}
        </li>
      ))}
    </ul>
  );
}

/** The same numbers as a table, behind a disclosure. */
function TableView<T extends Record<string, unknown>>({ caption, data, x, series, format }: {
  caption: string; data: T[]; x: keyof T & string; series: Series[]; format: (v: number) => string;
}) {
  return (
    <details className="mt-2 text-sm">
      <summary className="cursor-pointer text-muted hover:text-fg">Show as table</summary>
      <div className="mt-2 max-h-72 overflow-auto rounded-lg border border-border">
        <table className="w-full text-left" aria-label={caption}>
          <thead className="bg-surface-2 text-xs text-muted">
            <tr><th scope="col" className="px-3 py-1.5 font-medium">Period</th>
              {series.map((s) => <th key={s.key} scope="col" className="px-3 py-1.5 text-right font-medium">{s.label}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data.map((row) => (
              <tr key={String(row[x])}>
                <td className="px-3 py-1.5">{period(String(row[x]))}</td>
                {series.map((s) => <td key={s.key} className="px-3 py-1.5 text-right tabular-nums">{format(Number(row[s.key]))}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** One measure over time as bars (a single series: the title names it, so no legend). */
export function PeriodBars<T extends Record<string, unknown>>({ title, data, x, series, format = (v) => usd(v), axisFormat = tick }: {
  title: string; data: T[]; x: keyof T & string; series: Series; format?: (v: number) => string; axisFormat?: (v: unknown) => string;
}) {
  return (
    <figure>
      <figcaption className="sr-only">{title}</figcaption>
      <div className="h-56" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap={2}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey={x as string} tickFormatter={(v) => period(String(v))} {...axis} minTickGap={16} />
            <YAxis tickFormatter={axisFormat} allowDecimals={axisFormat === tick} {...axis} axisLine={false} width={56} />
            <Tooltip cursor={{ fill: "var(--surface-2)" }} content={<ChartTooltip series={[series]} format={format} />} />
            <Bar dataKey={series.key} name={series.label} fill={`var(--${series.color})`} radius={[4, 4, 0, 0]} maxBarSize={32}
              isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableView caption={title} data={data} x={x} series={[series]} format={format} />
    </figure>
  );
}

/** Two or more measures of the same unit over time as lines, with a legend and end labels. */
export function PeriodLines<T extends Record<string, unknown>>({ title, data, x, series, format = (v) => usd(v), axisFormat = tick }: {
  title: string; data: T[]; x: keyof T & string; series: Series[]; format?: (v: number) => string; axisFormat?: (v: unknown) => string;
}) {
  const last = data.length - 1;
  return (
    <figure>
      <figcaption className="sr-only">{title}</figcaption>
      <Legend series={series} />
      <div className="h-56" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 96, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey={x as string} tickFormatter={(v) => period(String(v))} {...axis} minTickGap={16} />
            <YAxis tickFormatter={axisFormat} allowDecimals={axisFormat === tick} {...axis} axisLine={false} width={56} />
            <Tooltip cursor={{ stroke: "var(--border-strong)" }} content={<ChartTooltip series={series} format={format} />} />
            {series.map((s) => (
              <Line key={s.key} type="linear" dataKey={s.key} name={s.label} stroke={`var(--${s.color})`} strokeWidth={2}
                dot={false} activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }} isAnimationActive={false}>
                <LabelList dataKey={s.key} content={({ index, x: lx, y: ly }) => index === last ? (
                  <text x={Number(lx) + 6} y={Number(ly)} dy={4} fontSize={11} fill="var(--muted)">{s.label}</text>
                ) : null} />
              </Line>
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <TableView caption={title} data={data} x={x} series={series} format={format} />
    </figure>
  );
}

/** A ranked breakdown: one bar per row, length relative to the largest, value as text. */
export function BarList({ label, rows, format = (v) => usd(v), names = {} }: {
  label: string; rows: { key: string; value: number; sub?: string }[]; format?: (v: number) => string; names?: Record<string, string>;
}) {
  if (rows.length === 0) return <p className="text-sm text-muted">Nothing in this range.</p>;
  const max = Math.max(...rows.map((r) => r.value), 0) || 1;
  return (
    <ul className="space-y-2" aria-label={label}>
      {rows.map((r) => (
        <li key={r.key} className="text-sm">
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-fg">{names[r.key] ?? r.key}</span>
            <span className="shrink-0 tabular-nums text-fg">{format(r.value)}{r.sub && <span className="ml-1 text-xs text-muted">{r.sub}</span>}</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-surface-2" aria-hidden="true">
            <div className="h-1.5 rounded-full bg-series-1" style={{ width: r.value > 0 ? `${Math.max(1, (r.value / max) * 100)}%` : 0 }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Spend against a budget, with the state in words (status colour is never the only signal). */
export function BudgetMeter({ label, spent, budget }: { label: string; spent: number; budget: number }) {
  const used = budget > 0 ? spent / budget : 0;
  const tone = used >= 1 ? "bg-bad" : used >= 0.8 ? "bg-warn" : "bg-ok";
  const state = used >= 1 ? "Over budget" : used >= 0.8 ? "Near budget" : "Within budget";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium text-fg">{label}</span>
        <span className="tabular-nums text-fg">{usd(spent)} <span className="text-muted">of {usd(budget)}</span></span>
      </div>
      <div className="mt-1.5 h-2 rounded-full bg-surface-2" role="meter" aria-label={label} aria-valuemin={0}
        aria-valuemax={budget} aria-valuenow={Math.min(spent, budget)} aria-valuetext={`${pct(used)} used: ${state.toLowerCase()}`}>
        <div className={`h-2 rounded-full ${tone}`} style={{ width: `${Math.min(100, used * 100)}%` }} />
      </div>
      <p className="mt-1 text-xs text-muted">{pct(used)} used · {state}</p>
    </div>
  );
}
