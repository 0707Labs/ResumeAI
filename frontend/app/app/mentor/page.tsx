"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { useHydrated } from "@/components/AppShell";
import { AlertIcon, ArrowRightIcon, CheckIcon, InfoIcon } from "@/components/icons";
import { ActionItem, CheckItem, GapRow, MentorCard, VerdictCard } from "@/components/MentorCard";
import { Alert, Button, Card, Spinner } from "@/components/ui";
import { api, messageFor } from "@/lib/api";
import type { MentorAdvice } from "@/lib/schemas";
import { useSession } from "@/lib/store";

type TalkingPoint = MentorAdvice["talking_points"][number];

export default function MentorPage() {
  const hydrated = useHydrated();
  const { resume, jd, analysis, score, mentor, setMentor } = useSession();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const load = useCallback(async () => {
    if (!resume || !jd || !analysis) return;
    setLoading(true);
    setError(null);
    try {
      setMentor(await api.mentor(resume, jd, analysis, score?.before ?? null));
    } catch (e) {
      setError(messageFor(e));
    } finally {
      setLoading(false);
    }
  }, [resume, jd, analysis, score, setMentor]);

  useEffect(() => {
    if (!hydrated || started.current || mentor || !analysis) return;
    started.current = true;
    void load();
  }, [hydrated, mentor, analysis, load]);

  if (!hydrated) return null;
  if (!analysis || !resume || !jd) {
    return <Alert tone="info" title="Nothing to talk through yet">Start on the <Link href="/app" className="font-medium text-accent underline">first step</Link>.</Alert>;
  }
  if (!mentor) {
    return (
      <Card>
        {loading ? (
          <p role="status" className="flex items-center gap-3 text-muted"><Spinner /> Putting your advice together…</p>
        ) : (
          <div className="space-y-3">
            {error && <Alert tone="bad" role="alert" title="We couldn't put the advice together">{error}</Alert>}
            <Button onClick={load}>Try again</Button>
          </div>
        )}
      </Card>
    );
  }
  return <Mentor advice={mentor} onRefresh={load} refreshing={loading} error={error} />;
}

function Mentor({ advice, onRefresh, refreshing, error }: {
  advice: MentorAdvice; onRefresh: () => void; refreshing: boolean; error: string | null;
}) {
  const { jd, checked, toggleChecked } = useSession();
  const tasks = advice.plan.weeks.flatMap((w) => w.tasks);
  const tasksDone = tasks.filter((t) => checked[`plan:${t.id}`]).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <h1 className="text-2xl font-semibold tracking-tight">Your mentor&apos;s take{jd?.title ? ` on ${jd.title}` : ""}</h1>
          <p className="mt-2 text-muted">What you bring, what&apos;s honestly missing, and what to do about it.</p>
        </div>
        <Button variant="ghost" onClick={onRefresh} busy={refreshing}>Refresh advice</Button>
      </div>
      {error && <Alert tone="bad" role="alert" title="Refresh didn't finish">{error}</Alert>}

      <VerdictCard verdict={advice.verdict} />

      <div className="grid gap-6 lg:grid-cols-2">
        <MentorCard id="strengths" title="What you bring" icon={<CheckIcon className="h-5 w-5 text-ok" />}
          intro="Start here. These already match the job, straight from your resume.">
          {advice.strengths.length ? (
            <ul className="space-y-3">
              {advice.strengths.map((s, i) => (
                <li key={i} className="flex gap-2 text-sm"><CheckIcon className="mt-0.5 h-4 w-4 text-ok" /><span>{s.text}</span></li>
              ))}
            </ul>
          ) : <p className="text-sm text-muted">Nothing lines up directly yet, and that&apos;s useful to know before you apply.</p>}
        </MentorCard>

        <MentorCard id="gaps" title="Honest gaps" icon={<AlertIcon className="h-5 w-5 text-warn" />}
          intro="Most important first. None of these were added to your resume.">
          {advice.gaps.length ? (
            <ul className="divide-y divide-border">{advice.gaps.map((g, i) => <GapRow key={i} gap={g} />)}</ul>
          ) : <p className="text-sm text-muted">No gaps worth worrying about.</p>}
        </MentorCard>
      </div>

      <MentorCard id="actions" title="Action plan" intro="Small steps first. Tick them off as you go; this stays in your browser tab.">
        <ul className="divide-y divide-border">
          {advice.actions.map((a) => (
            <ActionItem key={a.id} action={a} checked={!!checked[`action:${a.id}`]}
              onChange={(v) => toggleChecked(`action:${a.id}`, v)} />
          ))}
        </ul>
      </MentorCard>

      {advice.talking_points.length > 0 && <TalkingPoints points={advice.talking_points} />}

      <MentorCard id="plan" title="Two-week upskilling plan"
        intro={`${advice.plan.hours_per_day} a day, ten working days. Tick tasks off as you finish them.`}>
        <p className="mb-2 text-sm" aria-live="polite"><span className="font-medium">{tasksDone} of {tasks.length}</span> done</p>
        <div aria-hidden className="mb-4 h-2 overflow-hidden rounded-full bg-surface-2">
          <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${tasks.length ? (tasksDone / tasks.length) * 100 : 0}%` }} />
        </div>
        <div className="grid gap-6 md:grid-cols-2">
          {advice.plan.weeks.map((w) => (
            <div key={w.week}>
              <h3 className="font-semibold">Week {w.week}: {w.focus}</h3>
              <ul className="divide-y divide-border">
                {w.tasks.map((t) => (
                  <CheckItem key={t.id} id={`plan-${t.id}`} checked={!!checked[`plan:${t.id}`]}
                    onChange={(v) => toggleChecked(`plan:${t.id}`, v)}
                    meta={<><p>{t.detail}</p><p className="mt-1">Deliverable: {t.deliverable}</p></>}>
                    <span className="mr-2 text-xs font-semibold uppercase tracking-wide text-muted">{t.days}</span>
                    <span className="font-medium">{t.title}</span>
                  </CheckItem>
                ))}
              </ul>
            </div>
          ))}
        </div>
        {advice.plan.not_addressable.length > 0 && (
          <div className="mt-5 rounded-xl bg-surface-2 p-4 text-sm">
            <p className="flex items-center gap-2 font-medium"><InfoIcon /> Things two weeks can&apos;t fix</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-muted">{advice.plan.not_addressable.map((n) => <li key={n}>{n}</li>)}</ul>
          </div>
        )}
      </MentorCard>

      {advice.notes.length > 0 && <p className="text-xs text-muted">{advice.notes.join(" ")}</p>}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/app/score" className="text-sm text-accent underline-offset-2 hover:underline">Back to score</Link>
        <Link href="/app/export" className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-accent px-5 py-2 text-sm font-medium text-accent-fg hover:bg-accent-hover">
          Export your resume <ArrowRightIcon />
        </Link>
      </div>
    </div>
  );
}

const TP_GROUPS: { kind: TalkingPoint["kind"]; title: string }[] = [
  { kind: "strength", title: "Stories to tell" },
  { kind: "answer", title: "Things you told us" },
  { kind: "gap", title: "If a gap comes up" },
];

function TalkingPoints({ points }: { points: TalkingPoint[] }) {
  return (
    <details className="group rounded-2xl border border-border bg-surface p-5 sm:p-6" data-testid="talking-points">
      <summary className="cursor-pointer select-none text-lg font-semibold">
        Interview talking points <span className="text-sm font-normal text-muted">({points.length})</span>
      </summary>
      <p className="mt-1 text-sm text-muted">Prepare these out loud. Everything here comes from your resume or your own answers.</p>
      <div className="mt-4 space-y-5">
        {TP_GROUPS.map(({ kind, title }) => {
          const group = points.filter((p) => p.kind === kind);
          if (!group.length) return null;
          return (
            <div key={kind}>
              <h3 className="text-sm font-semibold uppercase tracking-wide text-muted">{title}</h3>
              <ul className="mt-2 space-y-3">
                {group.map((p) => (
                  <li key={p.id} className="rounded-xl bg-surface-2/60 p-3">
                    <p className="font-medium">{p.prompt}</p>
                    <p className="mt-1 text-sm text-muted">{p.detail}</p>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </details>
  );
}
