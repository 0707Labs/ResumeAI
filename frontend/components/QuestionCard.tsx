"use client";

import { useId } from "react";

import type { ClarifyingQuestion } from "@/lib/schemas";
import type { Answer, AnswerChoice } from "@/lib/store";

import { CheckIcon } from "./icons";
import { inputClass } from "./ui";

export const MIN_DESCRIPTION = 15;

/** Resolved means the candidate made a choice we can act on. */
export function isResolved(a: Answer | undefined): boolean {
  if (!a) return false;
  if (a.choice === "yes") return a.text.trim().length >= MIN_DESCRIPTION;
  return true;
}

// The backend's question ends with "If not, just say no." The buttons say that.
export function promptText(q: ClarifyingQuestion): string {
  return q.question.replace(/\s*If not, just say no\.?\s*$/i, "").trim();
}

const CHOICES: { value: AnswerChoice; label: string }[] = [
  { value: "yes", label: "Yes, I'll describe it" },
  { value: "no", label: "No" },
  { value: "skip", label: "Skip" },
];

export function QuestionCard({ question, value, onChange, optional = false }: {
  question: ClarifyingQuestion;
  value: Answer | undefined;
  onChange: (a: Answer) => void;
  optional?: boolean;
}) {
  const textId = useId();
  const hintId = useId();
  const choice = value?.choice;
  const text = value?.text ?? "";
  const tooShort = choice === "yes" && text.trim().length < MIN_DESCRIPTION;

  return (
    <fieldset className="mt-3 rounded-xl border border-border bg-surface-2/60 p-4" data-testid={`question-${question.id}`}>
      <legend className="sr-only">Question {question.id}{optional ? " (optional)" : ""}</legend>
      <p className="text-sm text-fg">{promptText(question)}</p>

      <div role="radiogroup" aria-label="Your answer" className="mt-3 flex flex-wrap gap-2">
        {CHOICES.map((c) => {
          const selected = choice === c.value;
          return (
            <label key={c.value}
              className={`inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-focus ${
                selected ? "border-accent bg-accent-soft font-medium text-fg" : "border-border-strong bg-surface text-fg hover:bg-surface-2"
              }`}>
              <input
                type="radio"
                name={`answer-${question.id}`}
                value={c.value}
                checked={selected}
                onChange={() => onChange({ choice: c.value, text })}
                className="sr-only"
              />
              {selected && <CheckIcon className="h-3.5 w-3.5 text-accent" />}
              {c.label}
            </label>
          );
        })}
      </div>

      {choice === "yes" && (
        <div className="mt-3">
          <label htmlFor={textId} className="block text-sm font-medium">Where and how did you use it?</label>
          <textarea
            id={textId}
            value={text}
            onChange={(e) => onChange({ choice: "yes", text: e.target.value })}
            rows={3}
            maxLength={2000}
            aria-describedby={hintId}
            aria-invalid={tooShort && text.length > 0 ? true : undefined}
            placeholder="e.g. At my last job I used it to…, or in a side project I built…"
            className={inputClass}
          />
          <p id={hintId} className="mt-1 text-xs text-muted">
            {tooShort
              ? "A sentence about where and what you did is enough."
              : "Only what you write here can be used to add this to your resume, and you'll review the wording."}
          </p>
        </div>
      )}
      {choice === "no" && (
        <p className="mt-3 text-xs text-muted">Thanks for being straight with us. We won&apos;t add it, and the mentor plan will cover it.</p>
      )}
      {choice === "skip" && (
        <p className="mt-3 text-xs text-muted">No problem. We&apos;ll leave it out for now; you can come back to it.</p>
      )}
    </fieldset>
  );
}
