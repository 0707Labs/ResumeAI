"use client";

import { useState } from "react";

import type { MentorAdvice } from "@/lib/types";

import { Button, Card, Empty, Note, Pill } from "./ui";

const VERDICT_STYLE: Record<MentorAdvice["verdict"]["decision"], { label: string; cls: string }> = {
  strong_fit: { label: "Strong fit", cls: "border-emerald-300 bg-emerald-50 text-emerald-900" },
  apply: { label: "Apply", cls: "border-sky-300 bg-sky-50 text-sky-900" },
  stretch: { label: "Stretch", cls: "border-amber-300 bg-amber-50 text-amber-900" },
  not_yet: { label: "Not yet", cls: "border-rose-300 bg-rose-50 text-rose-900" },
};

const SEVERITY_TONE = { critical: "rose", moderate: "amber", minor: "slate" } as const;

export function MentorStep({ advice, busy, ready, onRun }: {
  advice: MentorAdvice | null;
  busy: boolean;
  ready: boolean;
  onRun: () => void;
}) {
  const [done, setDone] = useState<Record<string, boolean>>({});
  return (
    <div className="space-y-5">
      <Card title="6. Mentor" actions={<Button onClick={onRun} busy={busy} disabled={!ready}>{advice ? "Refresh advice" : "Get advice"}</Button>}>
        {!ready && <Empty>Run the gap analysis and score first.</Empty>}
        {advice && (
          <div className={`rounded-lg border p-4 ${VERDICT_STYLE[advice.verdict.decision].cls}`}>
            <p className="text-xs font-semibold uppercase tracking-wide">Should you apply? {VERDICT_STYLE[advice.verdict.decision].label}</p>
            <p className="mt-1 text-lg font-semibold">{advice.verdict.headline}</p>
            <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm">{advice.verdict.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            <p className="mt-3 text-xs opacity-80">{advice.verdict.caveat}</p>
          </div>
        )}
        {advice?.notes.map((n) => <Note key={n}>{n}</Note>)}
      </Card>

      {advice && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card title="Strengths">
            <ul className="space-y-2 text-sm text-slate-700">
              {advice.strengths.map((s, i) => <li key={i}>✓ {s.text}</li>)}
              {!advice.strengths.length && <li className="text-slate-400">Nothing matched directly yet.</li>}
            </ul>
          </Card>
          <Card title="Gaps">
            <ul className="space-y-3 text-sm">
              {advice.gaps.map((g, i) => (
                <li key={i}>
                  <div className="flex items-center gap-2"><Pill tone={SEVERITY_TONE[g.severity]}>{g.severity}</Pill><b className="text-slate-800">{g.text}</b></div>
                  <p className="mt-0.5 text-slate-600">{g.why_it_matters}</p>
                </li>
              ))}
              {!advice.gaps.length && <li className="text-slate-400">No gaps found.</li>}
            </ul>
          </Card>
        </div>
      )}

      {advice && (
        <Card title="Actions" actions={<Pill>{Object.values(done).filter(Boolean).length}/{advice.actions.length} done</Pill>}>
          <ul className="space-y-2">
            {advice.actions.map((a) => (
              <li key={a.id} className="flex items-start gap-3 text-sm">
                <input type="checkbox" className="mt-1" checked={!!done[a.id]} onChange={(e) => setDone({ ...done, [a.id]: e.target.checked })} aria-label={`Mark ${a.id} done`} />
                <span className={done[a.id] ? "text-slate-400 line-through" : "text-slate-700"}>{a.text}</span>
                <span className="ml-auto shrink-0 text-xs text-slate-400">{a.effort}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {advice && (
        <Card title="Two-week plan" actions={<Pill>{advice.plan.hours_per_day} / day</Pill>}>
          {advice.plan.focus_skills.length > 0 && (
            <p className="mb-4 flex flex-wrap items-center gap-1.5 text-sm text-slate-600">Focus: {advice.plan.focus_skills.map((s) => <Pill key={s} tone="violet">{s}</Pill>)}</p>
          )}
          <div className="grid gap-5 md:grid-cols-2">
            {advice.plan.weeks.map((w) => (
              <div key={w.week}>
                <h3 className="text-sm font-semibold text-slate-900">Week {w.week}: {w.focus}</h3>
                <ol className="mt-2 space-y-3 border-l border-slate-200 pl-4">
                  {w.tasks.map((t) => (
                    <li key={t.id} className="text-sm">
                      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{t.days}</p>
                      <p className="font-medium text-slate-800">{t.title}</p>
                      <p className="text-slate-600">{t.detail}</p>
                      <p className="mt-0.5 text-xs text-slate-500">Deliverable: {t.deliverable}</p>
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
          {advice.plan.not_addressable.length > 0 && (
            <div className="mt-5 rounded-lg bg-slate-50 p-3 text-sm">
              <p className="mb-1 font-medium text-slate-700">Not closable in two weeks</p>
              <ul className="list-disc space-y-0.5 pl-5 text-slate-600">{advice.plan.not_addressable.map((n) => <li key={n}>{n}</li>)}</ul>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
