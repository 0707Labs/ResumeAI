"use client";

import type { GapAnalysis, GapItem, GapStatus } from "@/lib/types";

import { Button, Card, Empty, Note, Pill } from "./ui";

const STATUS_TONE: Record<GapStatus, "green" | "amber" | "rose"> = {
  evidenced: "green",
  implied: "amber",
  missing: "rose",
};

export function GapStep({ analysis, answers, setAnswer, busy, onAnalyze, onSaveAnswers, ready }: {
  analysis: GapAnalysis | null;
  answers: Record<string, string>;
  setAnswer: (qid: string, text: string) => void;
  busy: boolean;
  ready: boolean;
  onAnalyze: () => void;
  onSaveAnswers: () => void;
}) {
  const dirty = analysis?.items.some((i) => i.question && (answers[i.question.id] ?? "") !== (i.question.answer ?? ""));
  return (
    <div className="space-y-5">
      <Card title="3. Gap analysis" actions={<Button onClick={onAnalyze} busy={busy && !analysis} disabled={!ready}>{analysis ? "Re-run" : "Analyze"}</Button>}>
        {!ready && <Empty>Upload a resume and parse a JD first.</Empty>}
        {analysis && (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Pill tone="green">{analysis.counts.evidenced} evidenced</Pill>
            <Pill tone="amber">{analysis.counts.implied} implied</Pill>
            <Pill tone="rose">{analysis.counts.missing} missing</Pill>
            <span className="text-slate-600">Required coverage: <b>{Math.round(analysis.required_coverage * 100)}%</b></span>
            {analysis.candidate_years_experience != null && (
              <span className="text-slate-600">· ~{analysis.candidate_years_experience} years dated experience</span>
            )}
            {analysis.notes.map((n) => <Note key={n}>{n}</Note>)}
          </div>
        )}
      </Card>

      {analysis && (
        <Card title="Requirements" actions={
          <Button variant="success" onClick={onSaveAnswers} busy={busy} disabled={!dirty}>Save answers</Button>
        }>
          <Note>
            Missing requirements become questions. Only your own answers can add a fact. Say no if it isn&apos;t true;
            that&apos;s useful too, since it shapes the mentor plan.
          </Note>
          <ul className="mt-4 divide-y divide-slate-100">
            {analysis.items.map((item) => (
              <GapRow key={item.requirement_id} item={item} answer={item.question ? answers[item.question.id] ?? "" : ""} setAnswer={setAnswer} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function GapRow({ item, answer, setAnswer }: { item: GapItem; answer: string; setAnswer: (qid: string, t: string) => void }) {
  const q = item.question;
  return (
    <li className="py-4">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={STATUS_TONE[item.status]}>{item.status}</Pill>
        <Pill tone={item.priority === "required" ? "slate" : "blue"}>{item.priority}</Pill>
        {item.decided_by === "llm" && <Pill tone="violet" title="Claude reviewed this item">Claude</Pill>}
        <span className="text-sm font-medium text-slate-900">{item.requirement_text}</span>
      </div>
      <p className="mt-1 text-sm text-slate-600">{item.rationale}</p>
      {(item.evidence_bullet_ids.length > 0 || item.evidence_entry_ids.length > 0) && (
        <p className="mt-1 text-xs text-slate-400">Evidence: {[...item.evidence_bullet_ids, ...item.evidence_entry_ids, ...item.evidence_skills].join(", ")}</p>
      )}
      {q && (
        <div className="mt-3 rounded-lg bg-slate-50 p-3">
          <label htmlFor={q.id} className="block text-sm text-slate-800">
            <code className="mr-1 text-xs text-slate-400">{q.id}</code>{q.question}
          </label>
          <textarea
            id={q.id}
            value={answer}
            onChange={(e) => setAnswer(q.id, e.target.value)}
            rows={2}
            maxLength={2000}
            placeholder="Your answer (or 'No')"
            className="mt-2 w-full rounded-md border border-slate-300 bg-white p-2 text-sm focus:border-slate-900 focus:outline-none"
          />
          {q.answer_kind !== "unanswered" && (
            <p className="mt-1 text-xs text-slate-500">
              Saved as <b>{q.answer_kind}</b>
              {q.answer_kind === "confirmed" && ". Tailoring may now cite this answer."}
            </p>
          )}
        </div>
      )}
    </li>
  );
}
