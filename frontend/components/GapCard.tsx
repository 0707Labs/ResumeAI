"use client";

import { useState } from "react";

import type { GapItem, Resume } from "@/lib/schemas";
import type { Answer } from "@/lib/store";

import { QuestionCard } from "./QuestionCard";
import { PriorityBadge, StatusBadge } from "./StatusBadge";

type Evidence = { id: string; text: string };

function evidenceFor(item: GapItem, resume: Resume | null): Evidence[] {
  const out: Evidence[] = [];
  const bullets = new Map(resume?.sections.flatMap((s) => s.entries.flatMap((e) => e.bullets.map((b) => [b.id, b.text] as const))) ?? []);
  const entries = new Map(resume?.sections.flatMap((s) => s.entries.map((e) => [e.id, e] as const)) ?? []);
  for (const id of item.evidence_bullet_ids) out.push({ id, text: bullets.get(id) ?? "(not found in your resume)" });
  for (const id of item.evidence_entry_ids) {
    const e = entries.get(id);
    out.push({ id, text: e ? [e.title, e.organization].filter(Boolean).join(", ") : "(not found)" });
  }
  for (const skill of item.evidence_skills) out.push({ id: "skills", text: `Listed in your skills: ${skill}` });
  return out;
}

export function GapCard({ item, resume, answer, onAnswer }: {
  item: GapItem;
  resume: Resume | null;
  answer: Answer | undefined;
  onAnswer: (a: Answer) => void;
}) {
  const evidence = evidenceFor(item, resume);
  const optionalQuestion = item.status !== "missing" && item.question;
  const [open, setOpen] = useState(!!answer);

  return (
    <li className="rounded-xl border border-border bg-surface p-4" data-testid={`gap-${item.requirement_id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={item.status} />
        <PriorityBadge priority={item.priority} />
      </div>
      <p className="mt-2 font-medium text-fg">{item.requirement_text}</p>
      <p className="mt-1 text-sm text-muted">{item.rationale}</p>

      {evidence.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer select-none text-accent">
            Evidence:{" "}
            {evidence.map((e, i) => (
              <code key={`${e.id}-${i}`} className="mr-1 rounded bg-surface-2 px-1.5 py-0.5 text-xs text-fg">{e.id}</code>
            ))}
            <span className="sr-only"> (show the matching lines)</span>
          </summary>
          <ul className="mt-2 space-y-1 border-l-2 border-border pl-3">
            {evidence.map((e, i) => (
              <li key={`${e.id}-${i}`}>
                <code className="mr-2 text-xs text-muted">{e.id}</code>
                <span>{e.text}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {item.status === "missing" && item.question && (
        <QuestionCard question={item.question} value={answer} onChange={onAnswer} />
      )}

      {optionalQuestion && item.question && (
        open ? (
          <QuestionCard question={item.question} value={answer} onChange={onAnswer} optional />
        ) : (
          <button type="button" onClick={() => setOpen(true)}
            className="mt-2 text-sm text-accent underline-offset-2 hover:underline">
            {item.status === "implied" ? "Confirm this directly (optional)" : "Add a concrete example (optional)"}
          </button>
        )
      )}
    </li>
  );
}
