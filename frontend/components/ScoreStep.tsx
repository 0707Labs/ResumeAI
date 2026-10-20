"use client";

import type { ScoreComponent, ScoreResponse } from "@/lib/types";

import { Button, Card, Empty, Note, Pill } from "./ui";

const LABELS: Record<string, string> = {
  required_keywords: "Required keywords",
  preferred_keywords: "Preferred keywords",
  semantic_relevance: "Semantic relevance",
  title_seniority: "Title & seniority",
  format_parseability: "Format & parseability",
  quantified_impact: "Quantified impact",
};

export function ScoreStep({ score, busy, ready, onScore }: {
  score: ScoreResponse | null;
  busy: boolean;
  ready: boolean;
  onScore: () => void;
}) {
  return (
    <div className="space-y-5">
      <Card title="5. ATS score" actions={<Button onClick={onScore} busy={busy} disabled={!ready}>{score ? "Re-score" : "Score"}</Button>}>
        {!ready && <Empty>Upload a resume and parse a JD first.</Empty>}
        {score && (
          <div className="flex flex-wrap items-end gap-8">
            <Total label="Original" value={score.before.total} />
            {score.after && (
              <>
                <Total label="Tailored" value={score.after.total} />
                <div className="pb-2">
                  <Pill tone={(score.delta ?? 0) > 0 ? "green" : (score.delta ?? 0) < 0 ? "rose" : "slate"}>
                    {(score.delta ?? 0) > 0 ? "+" : ""}{score.delta} pts
                  </Pill>
                </div>
              </>
            )}
          </div>
        )}
        {score?.after && (
          <Note>
            &ldquo;Tailored&rdquo; counts verified bullets you haven&apos;t rejected (approved and pending). Verification is
            redone on the server, so nothing unverified can raise the score.
          </Note>
        )}
      </Card>

      {score && (
        <Card title="Breakdown">
          <div className="space-y-4">
            {score.before.components.map((c) => (
              <ComponentRow key={c.name} before={c} after={score.after?.components.find((a) => a.name === c.name) ?? null} />
            ))}
          </div>
          <p className="mt-5 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">{score.before.disclaimer}</p>
        </Card>
      )}
    </div>
  );
}

function Total({ label, value }: { label: string; value: number }) {
  const tone = value >= 75 ? "text-emerald-600" : value >= 55 ? "text-amber-600" : "text-rose-600";
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`text-4xl font-semibold tabular-nums ${tone}`}>{value.toFixed(1)}<span className="text-lg text-slate-400">/100</span></p>
    </div>
  );
}

function ComponentRow({ before, after }: { before: ScoreComponent; after: ScoreComponent | null }) {
  const shown = after ?? before;
  const max = shown.weight * 100;
  return (
    <details className="group rounded-lg border border-slate-200 p-3">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-3">
        <span className="w-44 text-sm font-medium text-slate-800">{LABELS[before.name] ?? before.name}</span>
        <div className="relative h-2.5 min-w-40 flex-1 overflow-hidden rounded-full bg-slate-100">
          <div className="absolute inset-y-0 left-0 rounded-full bg-slate-300" style={{ width: `${before.score * 100}%` }} />
          {after && <div className="absolute inset-y-0 left-0 rounded-full bg-slate-900" style={{ width: `${after.score * 100}%` }} />}
        </div>
        <span className="w-28 text-right text-sm tabular-nums text-slate-700">
          {after && after.points !== before.points ? <><s className="text-slate-400">{before.points}</s> {after.points}</> : shown.points}
          <span className="text-slate-400"> / {max}</span>
        </span>
        <Pill tone={shown.deterministic ? "slate" : "violet"} title={shown.deterministic ? "Same input, same score" : "Judged by Claude"}>
          {shown.deterministic ? "rules" : "Claude"}
        </Pill>
      </summary>
      <div className="mt-3 grid gap-3 text-sm md:grid-cols-2">
        <List title="Matched" items={shown.matched} tone="text-emerald-700" />
        <List title="Missing" items={shown.missing} tone="text-rose-700" />
      </div>
      {shown.notes && <p className="mt-2 text-xs text-slate-600">{shown.notes}</p>}
    </details>
  );
}

function List({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  return (
    <div>
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
      {items.length ? (
        <ul className={`space-y-0.5 ${tone}`}>{items.map((i) => <li key={i}>{i}</li>)}</ul>
      ) : <p className="text-slate-400">—</p>}
    </div>
  );
}

