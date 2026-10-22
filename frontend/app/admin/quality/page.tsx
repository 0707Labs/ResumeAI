"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { BarList, PeriodLines, StatTile, count, pct } from "@/components/admin/charts";
import { Pill, day } from "@/components/admin/ui";
import { ErrorState, PageHeader, Skeleton } from "@/components/app/states";
import { Alert, Button, Card } from "@/components/ui";
import { adminApi, adminError } from "@/lib/adminApi";
import { api } from "@/lib/api";
import { can } from "@/lib/roles";
import type { AdminQuality, Me } from "@/lib/schemas";

const RANGES = [7, 30, 90] as const;
const WARNINGS: Record<string, string> = {
  tables_detected: "Tables in the file", images_detected: "Images in the file", multi_column_suspected: "Looks multi-column",
  no_sections_found: "No sections found", no_bullets_found: "No bullets found", contact_missing: "No contact details",
  name_not_found: "No name found",
};
const FAILURES: Record<string, string> = { "413": "File too large", "415": "File type not supported", "422": "No readable text" };

/** Product safety: how often the verifier steps in, what people do about it, and how parsing goes. Counts only. */
export default function AdminQualityPage() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<AdminQuality | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.me().then(setMe).catch(() => setMe(null)); }, []);
  const load = useCallback(() => {
    setError(null);
    adminApi.quality(days).then(setData).catch((e) => setError(adminError(e)));
  }, [days]);
  useEffect(() => { if (can(me, "quality.read")) load(); }, [me, load]);

  if (me === undefined) return null;
  if (!can(me, "quality.read")) return <Alert tone="info" title="Not available for your role">Quality needs an admin.</Alert>;

  return (
    <div className="space-y-6">
      <PageHeader title="Quality" intro="How the fabrication verifier is doing, from counts kept on each analysis. No resume or job text is stored for this."
        actions={
          <div role="group" aria-label="Date range" className="flex gap-1">
            {RANGES.map((r) => (
              <Button key={r} variant={r === days ? "primary" : "secondary"} className="min-h-9 px-3" aria-pressed={r === days}
                onClick={() => setDays(r)}>{r} days</Button>
            ))}
          </div>
        } />
      {error && <ErrorState message={error} onRetry={load} />}
      {!data && !error && <div className="grid gap-3 sm:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}</div>}
      {data && <Body data={data} />}
    </div>
  );
}

function Body({ data }: { data: AdminQuality }) {
  const t = data.verifier.totals;
  const r = data.verifier.rates;
  const p = data.parsing;
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Bullets tailored" value={count(t.bullets_generated ?? 0)} sub={`${count(t.analyses_tailored ?? 0)} tailorings`} />
        <StatTile label="Flagged for review" value={pct(r.flagged)} sub={`${count(t.bullets_flagged ?? 0)} bullets with a warning`} />
        <StatTile label="Rewrites blocked" value={pct(r.blocked)} sub={`${count(t.bullets_blocked ?? 0)} refused by the verifier`} />
        <StatTile label="Overrides" value={pct(r.override)} sub={`${count(t.flag_overrides ?? 0)} flagged bullets approved anyway`} />
      </div>
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Verifier over time</h2>
        <p className="mb-3 text-sm text-muted">
          At download: {count(t.bullets_approved ?? 0)} bullets approved, {count(t.bullets_rejected ?? 0)} rejected,
          across {count(t.analyses_downloaded ?? 0)} downloaded tailorings.
        </p>
        <PeriodLines title="Flagged and overridden bullets by day" data={data.verifier.trend} x="day" format={count} axisFormat={count}
          series={[{ key: "flagged", label: "Flagged", color: "series-1" }, { key: "overrides", label: "Approved anyway", color: "series-2" }]} />
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-1 text-lg font-semibold">Resume parsing</h2>
          <p className="mb-3 text-sm text-muted">
            {count(p.attempts)} uploads, {pct(p.failure_rate)} failed. Warnings mean the parse may be incomplete.
          </p>
          <h3 className="mb-2 text-sm font-medium">Failures</h3>
          <BarList label="Parse failures" format={count} names={FAILURES}
            rows={Object.entries(p.failed).map(([k, v]) => ({ key: k, value: v }))} />
          <h3 className="mb-2 mt-4 text-sm font-medium">Warnings</h3>
          <BarList label="Parse warnings" format={count} names={WARNINGS}
            rows={Object.entries(p.warnings).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ key: k, value: v }))} />
        </Card>
        <Card>
          <h2 className="mb-1 text-lg font-semibold">ATS score lift</h2>
          <p className="mb-3 text-sm text-muted">After minus before, per tailoring. Median {data.ats_lift.median ?? "—"} points.</p>
          <BarList label="ATS lift distribution" format={count}
            rows={data.ats_lift.buckets.map((b) => ({ key: b.label, value: b.count }))} names={{ "below 0": "Lower than before" }} />
        </Card>
      </div>
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Fabrication reports</h2>
        <p className="mb-3 text-sm text-muted">From the support form. Each one is a candidate test case for the verifier; close the ticket once it&apos;s covered.</p>
        {data.fabrication_reports.length === 0 ? <p className="text-sm text-muted">No reports.</p> : (
          <ul className="divide-y divide-border text-sm" aria-label="Fabrication reports">
            {data.fabrication_reports.map((f) => (
              <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <Link href={`/admin/support/${f.id}`} className="font-medium text-accent underline">{f.subject}</Link>
                <span className="flex items-center gap-2 text-muted">{day(f.created_at)}
                  <Pill tone={f.status === "closed" ? "ok" : "warn"}>{f.status}</Pill></span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
