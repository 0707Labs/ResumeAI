"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import type { MentorAdvice } from "@/lib/schemas";

import { AlertIcon, ArrowRightIcon, CheckIcon, ErrorIcon, InfoIcon } from "./icons";

type Decision = MentorAdvice["verdict"]["decision"];
type Gap = MentorAdvice["gaps"][number];
type Action = MentorAdvice["actions"][number];

/** A titled section of mentor advice. */
export function MentorCard({ title, intro, icon, children, id }: {
  title: string;
  intro?: string;
  icon?: ReactNode;
  children: ReactNode;
  id: string;
}) {
  return (
    <section aria-labelledby={id} className="rounded-2xl border border-border bg-surface p-5 sm:p-6">
      <h2 id={id} className="flex items-center gap-2 text-lg font-semibold">{icon}{title}</h2>
      {intro && <p className="mt-1 text-sm text-muted">{intro}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export const VERDICT: Record<Decision, { label: string; cls: string; Icon: typeof CheckIcon }> = {
  strong_fit: { label: "Strong fit", cls: "border-ok/40 bg-ok-bg text-ok", Icon: CheckIcon },
  apply: { label: "Worth a shot", cls: "border-accent/40 bg-accent-soft text-accent", Icon: ArrowRightIcon },
  stretch: { label: "Stretch", cls: "border-warn/40 bg-warn-bg text-warn", Icon: AlertIcon },
  not_yet: { label: "Not yet", cls: "border-bad/40 bg-bad-bg text-bad", Icon: InfoIcon },
};

export function VerdictCard({ verdict }: { verdict: MentorAdvice["verdict"] }) {
  const { label, cls, Icon } = VERDICT[verdict.decision];
  return (
    <section aria-labelledby="verdict-heading" className={`rounded-2xl border p-5 sm:p-6 ${cls}`} data-testid="verdict">
      <h2 id="verdict-heading" className="text-sm font-semibold uppercase tracking-wide">Should you apply?</h2>
      <p className="mt-2 flex items-center gap-2 text-2xl font-semibold">
        <Icon className="h-6 w-6" /> {label}
      </p>
      <p className="mt-3 max-w-3xl leading-relaxed text-fg">
        <span className="font-medium">{verdict.headline}</span> {verdict.reasons.join(" ")}
      </p>
      <p className="mt-3 text-xs text-fg/70">{verdict.caveat}</p>
    </section>
  );
}

const SEVERITY: Record<Gap["severity"], { word: string; cls: string; Icon: typeof CheckIcon }> = {
  critical: { word: "Important", cls: "text-bad", Icon: ErrorIcon },
  moderate: { word: "Worth fixing", cls: "text-warn", Icon: AlertIcon },
  minor: { word: "Minor", cls: "text-muted", Icon: InfoIcon },
};

export function GapRow({ gap }: { gap: Gap }) {
  const { word, cls, Icon } = SEVERITY[gap.severity];
  return (
    <li className="py-3">
      <p className="flex flex-wrap items-center gap-2">
        <span className={`inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide ${cls}`}>
          <Icon className="h-3.5 w-3.5" />{word}
        </span>
        <span className="font-medium">{gap.text}</span>
        {gap.priority && <span className="text-xs text-muted">{gap.priority === "required" ? "Required" : "Nice to have"}</span>}
      </p>
      <p className="mt-1 text-sm text-muted">{gap.why_it_matters}</p>
    </li>
  );
}

const ACTION_KIND: Record<Action["kind"], { label: string; href?: string; cta?: string }> = {
  answer_question: { label: "Answer a question", href: "/app/analysis", cta: "Go to questions" },
  resume_edit: { label: "Resume edit", href: "/app/review", cta: "Open review" },
  learn: { label: "Learn" },
  apply_strategy: { label: "When you apply" },
};

export function CheckItem({ id, checked, onChange, children, meta }: {
  id: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  children: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <li className="flex gap-3 py-3">
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
        className="mt-1 h-4 w-4 shrink-0 accent-[var(--accent)]" />
      <div className="min-w-0 flex-1">
        <label htmlFor={id} className={`cursor-pointer ${checked ? "text-muted line-through" : ""}`}>{children}</label>
        {meta && <div className="mt-1 text-xs text-muted">{meta}</div>}
      </div>
    </li>
  );
}

export function ActionItem({ action, checked, onChange }: { action: Action; checked: boolean; onChange: (v: boolean) => void }) {
  const kind = ACTION_KIND[action.kind];
  return (
    <CheckItem id={`action-${action.id}`} checked={checked} onChange={onChange}
      meta={<span className="flex flex-wrap items-center gap-x-3">
        <span>{kind.label}</span><span>About {action.effort}</span>
        {kind.href && <Link href={kind.href} className="text-accent underline-offset-2 hover:underline">{kind.cta}</Link>}
      </span>}>
      {action.text}
    </CheckItem>
  );
}
