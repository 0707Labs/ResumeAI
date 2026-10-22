"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EmptyState, ErrorState, LoadingStatus, PageHeader, Skeleton } from "@/components/app/states";
import { ArrowRightIcon, CheckIcon, LightbulbIcon } from "@/components/icons";
import { Card } from "@/components/ui";
import type { Dashboard } from "@/lib/schemas";
import { planLabel, userApi, userError } from "@/lib/user";

const day = (iso: string) => new Date(iso).toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" });
const primary = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-accent px-5 py-2 text-sm font-medium text-accent-fg hover:bg-accent-hover";
const link = "text-sm font-medium text-accent underline-offset-2 hover:underline";

const STATUS: Record<Dashboard["recent"][number]["status"], string> = {
  started: "Started", tailored: "Tailored", downloaded: "Downloaded",
};

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    userApi.dashboard().then(setData).catch((e) => setError(userError(e)));
  }, []);
  useEffect(load, [load]);

  if (error) return <><PageHeader title="Dashboard" /><ErrorState message={error} onRetry={load} /></>;
  if (!data) return <DashboardSkeleton />;

  const first = data.name?.trim().split(/\s+/)[0];
  const { plan, referrals } = data;
  return (
    <>
      <PageHeader title={first ? `Welcome back, ${first}` : "Welcome back"}
        intro="Tailor your resume to a job, honestly. You approve every change."
        actions={<Link href="/app/tailor" className={primary}>Tailor a resume<ArrowRightIcon /></Link>} />

      {(!data.has_resume || !data.has_preferences) && (
        <p className="mb-6 rounded-lg border border-border bg-surface px-4 py-3 text-sm text-muted">
          {!data.has_resume && !data.has_preferences ? "Add your base resume and what you're looking for"
            : !data.has_resume ? "Add your base resume" : "Tell us what you're looking for"} to save time on every tailoring.{" "}
          <Link href="/app/welcome" className={link}>Finish setup</Link>
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="font-medium text-fg">Recent tailorings</h2>
          </div>
          {data.recent.length === 0 ? (
            <EmptyState title="Nothing tailored yet"
              action={<Link href="/app/tailor" className={primary}>Tailor your first resume</Link>}>
              Paste a job description and your resume. We show what matches, ask about gaps, and never invent experience.
            </EmptyState>
          ) : (
            <ul className="divide-y divide-border">
              {data.recent.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-fg">{r.job_title ?? "Untitled role"}</p>
                    <p className="text-sm text-muted">{[r.company, day(r.created_at)].filter(Boolean).join(" · ")}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <AtsChange before={r.ats_before} after={r.ats_after} />
                    <span className="flex items-center gap-1 rounded-md bg-surface-2 px-2 py-0.5 text-xs text-fg">
                      {r.status === "downloaded" && <CheckIcon />}{STATUS[r.status]}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="font-medium text-fg">Your plan</h2>
          <p className="mt-2 text-2xl font-semibold text-fg">{planLabel(plan)}</p>
          <p className="mt-1 text-sm text-muted">
            {plan.kind === "pass" && plan.pass_downloads_left !== null && `${plan.pass_downloads_left} downloads left on your pass. `}
            {plan.kind !== "credits" && plan.credits > 0 && `${plan.credits} credit${plan.credits === 1 ? "" : "s"} too. `}
            {plan.kind === "free" && `Tailoring is free to try; the clean download needs a credit or a pass. Free tailorings reset on ${day(plan.resets_at)}.`}
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            {plan.kind === "free" && <Link href="/pricing" className={primary}>See plans</Link>}
            <Link href="/app/billing" className={`${link} self-center`}>Plan &amp; billing</Link>
          </div>
        </Card>

        <Card className="lg:col-span-2">
          <h2 className="flex items-center gap-2 font-medium text-fg"><LightbulbIcon />Mentor tip</h2>
          {data.last_tip ? (
            <>
              <p className="mt-2 text-fg">{data.last_tip.text}</p>
              <p className="mt-1 text-sm text-muted">
                From your tailoring for {[data.last_tip.job_title ?? "a role", data.last_tip.company].filter(Boolean).join(" at ")},{" "}
                {day(data.last_tip.created_at)}.
              </p>
            </>
          ) : (
            <p className="mt-2 text-sm text-muted">After your next tailoring, the mentor&apos;s first suggestion shows here.</p>
          )}
        </Card>

        {referrals.enabled && (
          <Card>
            <h2 className="font-medium text-fg">Invite friends</h2>
            <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-muted">Invites used</dt>
                <dd className="text-lg font-semibold text-fg">
                  {referrals.invites_per_user - referrals.invites_left}/{referrals.invites_per_user}
                </dd>
              </div>
              <div>
                <dt className="text-muted">Credits earned</dt>
                <dd className="text-lg font-semibold text-fg">{referrals.credits_earned}</dd>
              </div>
            </dl>
            <p className="mt-2 text-sm text-muted">{referrals.joined} joined · {referrals.rewarded} rewarded</p>
            <Link href="/app/invites" className={`${link} mt-3 inline-block`}>Your invite link</Link>
          </Card>
        )}
      </div>
    </>
  );
}

/** "62 → 78" with the change; the word says the direction, not only the colour. */
function AtsChange({ before, after }: { before: number | null; after: number | null }) {
  if (before === null) return <span className="text-xs text-muted">No score yet</span>;
  if (after === null) return <span className="text-sm text-fg">ATS {Math.round(before)}</span>;
  const [from, to] = [Math.round(before), Math.round(after)];
  const delta = to - from;  // from the shown numbers, so the sum adds up on screen
  return (
    <span className="text-sm text-fg" title="ATS score before and after tailoring">
      ATS {from} → {to}{" "}
      <span className={delta > 0 ? "text-ok" : "text-muted"}>({delta > 0 ? `up ${delta}` : delta < 0 ? `down ${-delta}` : "no change"})</span>
    </span>
  );
}

function DashboardSkeleton() {
  return (
    <>
      <LoadingStatus label="Loading your dashboard" />
      <div className="mb-6 space-y-2"><Skeleton className="h-8 w-64" /><Skeleton className="h-4 w-80 max-w-full" /></div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="space-y-3 lg:col-span-2"><Skeleton className="h-5 w-40" />{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</Card>
        <Card className="space-y-3"><Skeleton className="h-5 w-24" /><Skeleton className="h-8 w-40" /><Skeleton className="h-4" /></Card>
      </div>
    </>
  );
}
