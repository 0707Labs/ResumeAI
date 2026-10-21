"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useHydrated } from "@/components/AppShell";
import { GapCard } from "@/components/GapCard";
import { ArrowRightIcon } from "@/components/icons";
import { isResolved } from "@/components/QuestionCard";
import { STATUS } from "@/components/StatusBadge";
import { Alert, Button } from "@/components/ui";
import { api, messageFor } from "@/lib/api";
import type { GapItem, GapStatus } from "@/lib/schemas";
import { useSession } from "@/lib/store";

const GROUPS: { status: GapStatus; title: string; blurb: string }[] = [
  { status: "evidenced", title: "Already on your resume", blurb: "Your bullets show these directly." },
  { status: "implied", title: "Hinted at, not stated", blurb: "Related work suggests these, but the resume doesn't name them." },
  { status: "missing", title: "Not on your resume yet", blurb: "We couldn't find these. If you've done them, tell us; if not, that's okay." },
];

export default function AnalysisPage() {
  const hydrated = useHydrated();
  const router = useRouter();
  const { analysis, jd, resume, answers, setAnswer, setAnswered } = useSession();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!hydrated) return null;
  if (!analysis) {
    return (
      <Alert tone="info" title="Nothing to show yet">
        Start on the <Link href="/app" className="font-medium text-accent underline">first step</Link> with your resume
        and a job description.
      </Alert>
    );
  }

  const missing = analysis.items.filter((i) => i.status === "missing" && i.question);
  const resolved = missing.filter((i) => isResolved(answers[i.question!.id])).length;
  const remaining = missing.length - resolved;

  async function continueToTailoring() {
    if (!analysis || remaining > 0) return;
    setError(null);
    setSaving(true);
    try {
      // Send every choice made, including optional ones; "skip" clears earlier answers.
      const payload = Object.fromEntries(
        analysis.items
          .filter((i) => i.question && answers[i.question.id])
          .map((i) => {
            const a = answers[i.question!.id];
            return [i.question!.id, a.choice === "yes" && !isResolved(a) ? { choice: "skip" as const, text: "" } : a];
          }),
      );
      const updated = await api.submitAnswers(analysis, payload);
      setAnswered(updated);
      router.push("/app/review");
    } catch (e) {
      setError(messageFor(e));
    } finally {
      setSaving(false);
    }
  }

  const pct = Math.round(analysis.required_coverage * 100);

  return (
    <div className="space-y-6 pb-28">
      <div className="max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">
          How your resume lines up{jd?.title ? <> with <span className="text-accent">{jd.title}</span></> : ""}
          {jd?.company ? <span className="text-muted"> at {jd.company}</span> : ""}
        </h1>
        <p className="mt-2 text-muted">
          You cover about <span className="font-medium text-fg">{pct}%</span> of the required items (hinted ones count
          half). {missing.length > 0
            ? "A few quick questions below will help us tailor honestly."
            : "Nothing is missing outright, so there's nothing you need to answer."}
        </p>
        {analysis.notes.map((n) => <p key={n} className="mt-1 text-xs text-muted">{n}</p>)}
      </div>

      <dl className="grid grid-cols-3 gap-3">
        {GROUPS.map(({ status }) => {
          const { word, Icon, cls } = STATUS[status];
          return (
            <div key={status} className={`rounded-xl border px-4 py-3 ${cls}`}>
              <dt className="flex items-center gap-1.5 text-sm font-medium"><Icon className="h-4 w-4" />{word}</dt>
              <dd className="text-2xl font-semibold tabular-nums">{analysis.counts[status] ?? 0}</dd>
            </div>
          );
        })}
      </dl>

      {GROUPS.map(({ status, title, blurb }) => {
        const items: GapItem[] = analysis.items.filter((i) => i.status === status);
        if (!items.length) return null;
        const { Icon, word } = STATUS[status];
        return (
          <section key={status} aria-labelledby={`group-${status}`}>
            <h2 id={`group-${status}`} className="flex items-center gap-2 text-lg font-semibold">
              <Icon className="h-5 w-5" /> {title}
              <span className="sr-only"> ({word})</span>
              <span className="text-sm font-normal text-muted">· {items.length}</span>
            </h2>
            <p className="mb-3 text-sm text-muted">{blurb}</p>
            <ul className="space-y-3">
              {items.map((item) => (
                <GapCard
                  key={item.requirement_id}
                  item={item}
                  resume={resume}
                  answer={item.question ? answers[item.question.id] : undefined}
                  onAnswer={(a) => item.question && setAnswer(item.question.id, a)}
                />
              ))}
            </ul>
          </section>
        );
      })}

      <div className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-surface/95 backdrop-blur"
        style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}>
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="min-w-0 text-sm" aria-live="polite">
            {missing.length === 0 ? (
              <span className="text-muted">No questions to answer.</span>
            ) : (
              <span id="questions-progress">
                <span className="font-medium">{resolved} of {missing.length}</span> questions answered or skipped
                {remaining > 0 && <span className="text-muted">. {remaining} to go before tailoring.</span>}
              </span>
            )}
            {error && <div className="mt-2"><Alert tone="bad" role="alert" title="Couldn't save your answers">{error}</Alert></div>}
          </div>
          <Button onClick={continueToTailoring} busy={saving} disabled={remaining > 0}
            aria-describedby={missing.length ? "questions-progress" : undefined} className="shrink-0 px-6">
            Continue to tailoring <ArrowRightIcon />
          </Button>
        </div>
      </div>
    </div>
  );
}
