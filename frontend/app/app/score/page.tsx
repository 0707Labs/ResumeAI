"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useHydrated } from "@/components/AppShell";
import { BreakdownBars } from "@/components/BreakdownBars";
import { ArrowRightIcon, InfoIcon } from "@/components/icons";
import { KeywordChips } from "@/components/KeywordChips";
import { ScoreRing } from "@/components/ScoreRing";
import { Alert, Button, Card, Spinner } from "@/components/ui";
import { api, messageFor } from "@/lib/api";
import { counts, withDecisions } from "@/lib/review";
import { useSession } from "@/lib/store";

const DISCLAIMER = "Estimate only. Real ATS systems vary.";

export default function ScorePage() {
  const hydrated = useHydrated();
  const { resume, jd, analysis, tailored, decisions, score, setScore } = useSession();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!resume || !jd) return;
    setLoading(true);
    setError(null);
    try {
      const t = tailored ? withDecisions(tailored, decisions) : null;
      setScore(await api.score(resume, jd, t, analysis, { approvedOnly: true }));
    } catch (e) {
      setError(messageFor(e));
    } finally {
      setLoading(false);
    }
  }, [resume, jd, analysis, tailored, decisions, setScore]);

  // Always score what you'd export right now: approved changes only.
  useEffect(() => {
    if (hydrated) void refresh();
  }, [hydrated, refresh]);

  if (!hydrated) return null;
  if (!resume || !jd) {
    return <Alert tone="info" title="No score yet">Start on the <Link href="/app" className="font-medium text-accent underline">first step</Link>.</Alert>;
  }

  const approved = tailored ? counts(tailored, decisions).approved : 0;
  const before = score?.before;
  const after = score?.after ?? null;
  const delta = score?.delta ?? 0;
  const find = (n: string) => (after ?? before)?.components.find((c) => c.name === n) ?? null;

  return (
    <div className="space-y-6">
      <div className="max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">Your ATS estimate</h1>
        <p className="mt-2 text-muted">
          How a typical applicant tracking system might read your resume for this job, before and after the changes you approved.
        </p>
      </div>

      <div className="flex items-start gap-3 rounded-xl border border-border bg-surface-2 px-4 py-3 text-sm">
        <InfoIcon className="mt-0.5 h-5 w-5 text-accent" />
        <p>
          <span className="font-medium">{DISCLAIMER}</span>{" "}
          <span className="text-muted">{before?.disclaimer ?? ""} Use this to spot gaps, not as a pass/fail grade.</span>
        </p>
      </div>

      {error && (
        <Alert tone="bad" role="alert" title="We couldn't score this right now">
          {error} <Button variant="ghost" className="ml-1 min-h-8 px-2" onClick={refresh}>Try again</Button>
        </Alert>
      )}

      {!before ? (
        <Card><p role="status" className="flex items-center gap-3 text-muted"><Spinner /> Scoring your resume…</p></Card>
      ) : (
        <>
          <Card className="flex flex-col items-center gap-6 sm:flex-row sm:justify-center sm:gap-12" aria-labelledby="overall">
            <h2 id="overall" className="sr-only">Overall score</h2>
            <ScoreRing value={before.total} label="Your original resume" tone="muted" />
            <div className="text-center" aria-live="polite">
              {after ? (
                <p className={`text-lg font-semibold tabular-nums ${delta > 0 ? "text-ok" : delta < 0 ? "text-bad" : "text-muted"}`}>
                  {delta > 0 ? `+${delta.toFixed(1)} points` : delta < 0 ? `${delta.toFixed(1)} points` : "No change yet"}
                </p>
              ) : null}
              <ArrowRightIcon className="mx-auto mt-1 hidden h-6 w-6 text-muted sm:block" />
              {loading && <span className="mt-2 inline-block"><Spinner label="Updating score" /></span>}
            </div>
            <ScoreRing value={after?.total ?? before.total} label={`With your ${approved} approved change${approved === 1 ? "" : "s"}`} />
          </Card>

          {tailored && approved === 0 && (
            <Alert tone="info" title="No approved changes yet">
              Both scores match because nothing is approved. <Link href="/app/review" className="font-medium text-accent underline">Review your changes</Link> to see what they add.
            </Alert>
          )}

          <section aria-labelledby="breakdown-heading" className="space-y-3">
            <h2 id="breakdown-heading" className="text-lg font-semibold">Where the points come from</h2>
            <BreakdownBars before={before} after={after} />
          </section>

          <Card aria-labelledby="keywords-heading" className="space-y-6">
            <h2 id="keywords-heading" className="text-lg font-semibold">Keywords</h2>
            <p className="-mt-4 text-sm text-muted">
              A missing keyword is only worth adding if it&apos;s true. If it is, answer the matching question or edit a bullet on the review page.
            </p>
            <div className="grid gap-6 md:grid-cols-2">
              <KeywordChips title="Required" component={find("required_keywords")} />
              <KeywordChips title="Preferred" component={find("preferred_keywords")} />
            </div>
          </Card>
        </>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/app/review" className="text-sm text-accent underline-offset-2 hover:underline">Back to review</Link>
        <Link href="/app/mentor" className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-accent px-5 py-2 text-sm font-medium text-accent-fg hover:bg-accent-hover">
          Talk it through with the mentor <ArrowRightIcon />
        </Link>
      </div>
    </div>
  );
}
