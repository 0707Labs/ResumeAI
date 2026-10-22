"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { useHydrated } from "@/components/AppShell";
import { type ConfirmedAnswer, DiffBullet, SideBySide } from "@/components/DiffBullet";
import { ArrowRightIcon, CheckIcon, ErrorIcon } from "@/components/icons";
import { isResolved } from "@/components/QuestionCard";
import { Alert, Button, Card, Spinner } from "@/components/ui";
import { api, messageFor } from "@/lib/api";
import { counts, decisionOf, exportCheck, isChanged, isFlagged, withDecisions } from "@/lib/review";
import type { Entry, ReviewStatus, TailoredBullet } from "@/lib/schemas";
import { useSession } from "@/lib/store";

export default function ReviewPage() {
  const hydrated = useHydrated();
  const s = useSession();
  const [tailoring, setTailoring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const questionsDone = !!s.analysis && s.analysis.items
    .filter((i) => i.status === "missing" && i.question)
    .every((i) => isResolved(s.answers[i.question!.id]));

  async function runTailor() {
    if (!s.resume || !s.jd || !s.analysis) return;
    setError(null);
    setTailoring(true);
    try {
      s.setTailored(await api.tailor(s.resume, s.jd, s.analysis));
    } catch (e) {
      setError(messageFor(e));
    } finally {
      setTailoring(false);
    }
  }

  // First visit: draft the tailored bullets automatically.
  useEffect(() => {
    if (!hydrated || started.current || s.tailored || !s.analysis || !questionsDone) return;
    started.current = true;
    void runTailor();
  }); // runs after every render; the ref makes it fire once

  if (!hydrated) return null;
  if (!s.analysis || !s.resume || !s.jd) {
    return <Alert tone="info" title="Nothing to review yet">Start on the <Link href="/app/tailor" className="font-medium text-accent underline">first step</Link>.</Alert>;
  }
  if (!s.tailored && !questionsDone) {
    return (
      <Alert tone="info" title="A couple of questions first">
        Answer or skip the open questions on the <Link href="/app/tailor/analysis" className="font-medium text-accent underline">gaps page</Link>, then come back.
      </Alert>
    );
  }
  if (!s.tailored) {
    return (
      <Card>
        {tailoring ? (
          <p role="status" className="flex items-center gap-3 text-muted"><Spinner /> Drafting honest edits and checking each one against your resume…</p>
        ) : (
          <div className="space-y-3">
            {error && <Alert tone="bad" role="alert" title="We couldn't draft the edits">{error}</Alert>}
            <Button onClick={runTailor}>Try again</Button>
          </div>
        )}
      </Card>
    );
  }
  return <Review onRetailor={runTailor} retailoring={tailoring} retailorError={error} />;
}

function Review({ onRetailor, retailoring, retailorError }: { onRetailor: () => void; retailoring: boolean; retailorError: string | null }) {
  const s = useSession();
  const tailored = s.tailored!;
  const resume = s.resume!;
  const c = counts(tailored, s.decisions);
  const check = exportCheck(tailored, s.decisions);
  const eligible = tailored.bullets.filter((b) => isChanged(b) && !isFlagged(b) && decisionOf(b, s.decisions) === "pending").length;

  const answers: ConfirmedAnswer[] = (s.analysis?.items ?? [])
    .filter((i) => i.question?.answer && i.question.answer_kind === "confirmed")
    .map((i) => ({ id: i.question!.id, requirement: i.requirement_text, answer: i.question!.answer! }));

  async function edit(b: TailoredBullet, text: string, answerIds: string[]) {
    const draft = { ...b, text, source_answer_ids: answerIds, change_type: "reword" as const, review: "pending" as const };
    const res = await api.verify(resume, [draft], s.analysis, s.jd?.raw_text ?? "", null);
    s.replaceBullet(res.bullets[0]);
  }

  const entries: Entry[] = resume.sections.flatMap((sec) => sec.entries);
  const byEntry = new Map<string, TailoredBullet[]>();
  for (const b of tailored.bullets) {
    const key = b.entry_id ?? "other";
    byEntry.set(key, [...(byEntry.get(key) ?? []), b]);
  }

  return (
    <div className="space-y-6">
      <div className="max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">Review each change</h1>
        <p className="mt-2 text-muted">
          Nothing changes on your resume until you approve it. Anything you reject stays exactly as you wrote it.
        </p>
      </div>

      <ReviewBar
        changed={c.changed} approved={c.approved} rejected={c.rejected} pending={c.pending}
        eligible={eligible} exportOk={check.ok} unresolved={check.unresolved.length + (check.summaryUnresolved ? 1 : 0)}
        onApproveAll={s.approveAllVerified}
      />

      {tailored.notes.length > 0 && (
        <Alert tone="info" title="How these were drafted">
          <ul className="list-disc pl-4">{tailored.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </Alert>
      )}
      {c.changed === 0 && (
        <Alert tone="info" title="No rewrites to review">
          We didn&apos;t find a safe way to reword anything without adding facts. You can still edit any line yourself below,
          and we&apos;ll check it the same way.
        </Alert>
      )}
      {retailorError && <Alert tone="bad" role="alert" title="Re-drafting didn't finish">{retailorError}</Alert>}

      {tailored.summary && (
        <Card aria-labelledby="summary-heading">
          <h2 id="summary-heading" className="text-lg font-semibold">Summary</h2>
          <SideBySide before={resume.summary ?? ""} after={tailored.summary} />
          {!tailored.summary_verification?.passed && (
            <p className="mt-2 text-sm text-bad">The verifier blocked this summary, so it can only be rejected.</p>
          )}
          <div className="mt-3 flex gap-2">
            <Button variant={tailored.summary_review === "approved" ? "primary" : "secondary"} aria-pressed={tailored.summary_review === "approved"}
              disabled={!tailored.summary_verification?.passed}
              onClick={() => s.setSummaryReview(tailored.summary_review === "approved" ? "pending" : "approved")}>
              <CheckIcon /> {tailored.summary_review === "approved" ? "Approved" : "Approve"}
            </Button>
            <Button variant={tailored.summary_review === "rejected" ? "primary" : "secondary"} aria-pressed={tailored.summary_review === "rejected"}
              onClick={() => s.setSummaryReview(tailored.summary_review === "rejected" ? "pending" : "rejected")}>
              {tailored.summary_review === "rejected" ? "Keeping original" : "Reject (keep original)"}
            </Button>
          </div>
        </Card>
      )}

      {entries.filter((e) => byEntry.has(e.id)).map((e) => {
        const bullets = byEntry.get(e.id)!;
        const changed = bullets.filter(isChanged);
        const same = bullets.filter((b) => !isChanged(b));
        const row = (b: TailoredBullet) => (
          <DiffBullet key={b.id} bullet={b} decision={decisionOf(b, s.decisions)} answers={answers}
            edited={!!s.edited[b.id]}
            onDecide={(st: ReviewStatus) => s.decide(b.id, st)} onEdit={(t, ids) => edit(b, t, ids)} />
        );
        return (
          <section key={e.id} aria-labelledby={`entry-${e.id}`}>
            <h2 id={`entry-${e.id}`} className="text-lg font-semibold">
              {[e.title, e.organization].filter(Boolean).join(" · ") || e.id}
              {(e.start_date || e.end_date) && (
                <span className="ml-2 text-sm font-normal text-muted">{[e.start_date, e.end_date].filter(Boolean).join(" – ")}</span>
              )}
            </h2>
            {changed.length > 0 && <ul className="mt-3 space-y-3">{changed.map(row)}</ul>}
            {same.length > 0 && (
              <details className="mt-3 rounded-xl border border-border bg-surface p-4" open={changed.length === 0 && same.length <= 3}>
                <summary className="cursor-pointer select-none text-sm text-muted">
                  {same.length} line{same.length > 1 ? "s" : ""} kept as written (you can still edit them)
                </summary>
                <ul className="mt-3 space-y-3">{same.map(row)}</ul>
              </details>
            )}
          </section>
        );
      })}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="ghost" onClick={onRetailor} busy={retailoring}>Start over with fresh drafts</Button>
        <Link href="/app/tailor/score" className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-accent px-5 py-2 text-sm font-medium text-accent-fg hover:bg-accent-hover">
          See your score <ArrowRightIcon />
        </Link>
      </div>
    </div>
  );
}

function ReviewBar({ changed, approved, rejected, pending, eligible, exportOk, unresolved, onApproveAll }: {
  changed: number; approved: number; rejected: number; pending: number; eligible: number;
  exportOk: boolean; unresolved: number; onApproveAll: () => void;
}) {
  return (
    <div className="sticky top-0 z-10 -mx-4 border-y border-border bg-surface/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6"
      style={{ top: "env(safe-area-inset-top, 0px)" }} data-testid="review-bar">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <LiveScore />
        <p className="text-sm text-muted">
          <span className="font-medium text-fg">{approved}</span> approved · <span className="font-medium text-fg">{rejected}</span> kept original ·{" "}
          <span className="font-medium text-fg">{pending}</span> waiting{changed === 0 ? "" : ` (of ${changed})`}
        </p>
        <p className={`flex items-center gap-1.5 text-sm ${exportOk ? "text-ok" : "text-bad"}`} aria-live="polite">
          {exportOk ? <CheckIcon /> : <ErrorIcon />}
          {exportOk ? "Ready to export" : `${unresolved} flagged change${unresolved > 1 ? "s" : ""} need${unresolved > 1 ? "" : "s"} your decision before export`}
        </p>
        <Button variant="secondary" className="ml-auto" onClick={onApproveAll} disabled={eligible === 0}
          aria-describedby="approve-all-hint">
          <CheckIcon /> Approve all verified{eligible ? ` (${eligible})` : ""}
        </Button>
        <span id="approve-all-hint" className="sr-only">
          Approves only changes the verifier raised nothing about. Flagged ones always need your own decision.
        </span>
      </div>
    </div>
  );
}

/** ATS score for what you'd export right now (approved changes only). Debounced. */
function LiveScore() {
  const { resume, jd, analysis, tailored, decisions, score, setScore } = useSession();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const payload = useMemo(() => (tailored ? withDecisions(tailored, decisions) : null), [tailored, decisions]);

  useEffect(() => {
    if (!resume || !jd || !payload) return;
    const controller = new AbortController();
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        setScore(await api.score(resume, jd, payload, analysis, { approvedOnly: true, signal: controller.signal }));
        setFailed(false);
      } catch (e) {
        if (!(e instanceof DOMException && e.name === "AbortError")) setFailed(true);
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }, 350);
    return () => { clearTimeout(t); controller.abort(); };
  }, [resume, jd, analysis, payload, setScore]);

  const before = score?.before.total;
  const after = score?.after?.total;
  const delta = score?.delta ?? 0;
  return (
    <div className="flex items-baseline gap-2" aria-live="polite" aria-atomic="true" data-testid="live-score">
      <span className="text-sm text-muted">ATS estimate</span>
      {before == null ? (
        <span className="text-sm text-muted">{failed ? "unavailable" : "…"}</span>
      ) : (
        <>
          <span className="text-sm tabular-nums text-muted">{before.toFixed(1)}</span>
          <span aria-hidden className="text-muted">→</span>
          <span className="sr-only">with your approvals</span>
          <span className="text-xl font-semibold tabular-nums">{(after ?? before).toFixed(1)}</span>
          <span className={`text-sm tabular-nums ${delta > 0 ? "text-ok" : delta < 0 ? "text-bad" : "text-muted"}`}>
            {delta > 0 ? "+" : ""}{delta.toFixed(1)}
          </span>
        </>
      )}
      {busy && <Spinner label="Updating score" />}
    </div>
  );
}
