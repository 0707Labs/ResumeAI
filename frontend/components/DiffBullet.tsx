"use client";

import { useId, useState } from "react";

import { messageFor } from "@/lib/api";
import { wordDiff } from "@/lib/diff";
import { flagLabel, isBlocked, isChanged, whyThisChange } from "@/lib/review";
import type { ReviewStatus, TailoredBullet, VerificationFlag } from "@/lib/schemas";

import { AlertIcon, CheckIcon, ErrorIcon, InfoIcon } from "./icons";
import { Alert, Button, inputClass } from "./ui";
import { VerifierBadge } from "./VerifierBadge";

export type ConfirmedAnswer = { id: string; requirement: string; answer: string };

export function DiffBullet({ bullet, decision, answers, onDecide, onEdit, edited = false }: {
  bullet: TailoredBullet;
  decision: ReviewStatus;
  edited?: boolean;
  answers: ConfirmedAnswer[];
  onDecide: (status: ReviewStatus) => void;
  onEdit: (text: string, answerIds: string[]) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const changed = isChanged(bullet);
  const blocked = isBlocked(bullet);
  const flags = bullet.verification?.flags ?? [];
  const blockReasonId = useId();

  const frame = decision === "approved" ? "border-ok/50"
    : decision === "rejected" ? "border-border opacity-80"
    : blocked ? "border-bad/50" : flags.length ? "border-warn/50" : "border-border";

  return (
    <li className={`rounded-xl border bg-surface p-4 ${frame}`} data-testid={`bullet-${bullet.id}`}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <VerifierBadge bullet={bullet} />
        <span className="text-muted">
          From <code className="rounded bg-surface-2 px-1">{bullet.source_bullet_ids.join(", ") || "no source"}</code>
          {bullet.source_answer_ids.length > 0 && <> + your answer <code className="rounded bg-surface-2 px-1">{bullet.source_answer_ids.join(", ")}</code></>}
        </span>
        <DecisionTag decision={decision} changed={changed} />
      </div>

      {editing ? (
        <EditBox bullet={bullet} answers={answers} onCancel={() => setEditing(false)}
          onSave={async (text, ids) => { await onEdit(text, ids); setEditing(false); }} />
      ) : changed ? (
        <SideBySide before={bullet.original_text} after={bullet.text} />
      ) : (
        <p className="mt-3 text-sm text-fg">{bullet.text}</p>
      )}

      <p className="mt-3 flex gap-2 text-sm text-muted">
        <InfoIcon className="mt-0.5 h-4 w-4" />
        <span><span className="font-medium text-fg">Why this change:</span> {whyThisChange(bullet, edited)}</span>
      </p>

      {flags.length > 0 && <FlagList flags={flags} />}

      {bullet.rejected_attempts.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer select-none text-muted">
            We refused {bullet.rejected_attempts.length} earlier rewrite{bullet.rejected_attempts.length > 1 ? "s" : ""} that added things you didn&apos;t say
          </summary>
          <ul className="mt-2 space-y-2">
            {bullet.rejected_attempts.map((a, i) => (
              <li key={i} className="rounded-lg bg-surface-2 p-2">
                <p><del className="decoration-bad">{a.text}</del></p>
                <FlagList flags={a.flags.filter((f) => f.severity === "block")} compact label="Why it was refused" />
              </li>
            ))}
          </ul>
        </details>
      )}

      {!editing && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {changed && (
            <>
              <Button variant={decision === "approved" ? "primary" : "secondary"} aria-pressed={decision === "approved"}
                disabled={blocked} aria-describedby={blocked ? blockReasonId : undefined}
                onClick={() => onDecide(decision === "approved" ? "pending" : "approved")}>
                <CheckIcon /> {decision === "approved" ? "Approved" : "Approve"}
              </Button>
              <Button variant={decision === "rejected" ? "primary" : "secondary"} aria-pressed={decision === "rejected"}
                onClick={() => onDecide(decision === "rejected" ? "pending" : "rejected")}>
                {decision === "rejected" ? "Keeping original" : "Reject (keep original)"}
              </Button>
            </>
          )}
          <Button variant="ghost" onClick={() => setEditing(true)}>Edit manually</Button>
          {changed && blocked && (
            <p id={blockReasonId} className="w-full text-xs text-bad">
              Can&apos;t approve this as is: it says something your resume doesn&apos;t. Edit it, or keep the original.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

function DecisionTag({ decision, changed }: { decision: ReviewStatus; changed: boolean }) {
  if (!changed) return <span className="ml-auto text-muted">No change</span>;
  const map = {
    approved: { Icon: CheckIcon, text: "Approved", cls: "text-ok" },
    rejected: { Icon: ErrorIcon, text: "Keeping original", cls: "text-muted" },
    pending: { Icon: AlertIcon, text: "Waiting for you", cls: "text-muted" },
  } as const;
  const { Icon, text, cls } = map[decision];
  return <span className={`ml-auto inline-flex items-center gap-1 ${cls}`}><Icon className="h-3.5 w-3.5" />{text}</span>;
}

export function SideBySide({ before, after }: { before: string; after: string }) {
  const parts = wordDiff(before, after);
  return (
    <div className="mt-3 grid gap-3 md:grid-cols-2">
      <div className="rounded-lg bg-surface-2/60 p-3">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Original</p>
        <p className="text-sm leading-relaxed" data-testid="original">
          {parts.filter((p) => p.type !== "added").map((p, i) =>
            p.type === "removed" ? <del key={i}><span className="sr-only">removed: </span>{p.text}</del> : <span key={i}>{p.text}</span>)}
        </p>
      </div>
      <div className="rounded-lg bg-surface-2/60 p-3">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Tailored</p>
        <p className="text-sm leading-relaxed" data-testid="tailored">
          {parts.filter((p) => p.type !== "removed").map((p, i) =>
            p.type === "added" ? <ins key={i}><span className="sr-only">added: </span>{p.text}</ins> : <span key={i}>{p.text}</span>)}
        </p>
      </div>
    </div>
  );
}

function FlagList({ flags, compact = false, label = "What the verifier found" }: {
  flags: VerificationFlag[];
  compact?: boolean;
  label?: string;
}) {
  return (
    <ul className={`${compact ? "mt-1" : "mt-3"} space-y-1.5`} aria-label={label}>
      {flags.map((f, i) => {
        const block = f.severity === "block";
        const Icon = block ? ErrorIcon : AlertIcon;
        return (
          <li key={i} className={`flex gap-2 text-sm ${block ? "text-bad" : "text-warn"}`}>
            <Icon className="mt-0.5 h-4 w-4" />
            <span>
              <span className="font-medium">{block ? "Blocked" : "Check"}: {flagLabel(f)}</span>
              {f.token && <> <mark className="rounded bg-surface-2 px-1 text-fg">{f.token}</mark></>}
              {!compact && <span className="text-fg/80">. {f.detail}</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function EditBox({ bullet, answers, onSave, onCancel }: {
  bullet: TailoredBullet;
  answers: ConfirmedAnswer[];
  onSave: (text: string, answerIds: string[]) => Promise<void>;
  onCancel: () => void;
}) {
  const [text, setText] = useState(bullet.text);
  const [cited, setCited] = useState<string[]>(bullet.source_answer_ids);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = useId();
  return (
    <div className="mt-3 space-y-3">
      <p className="text-xs text-muted">Original: {bullet.original_text}</p>
      <div>
        <label htmlFor={id} className="block text-sm font-medium">Your wording</label>
        <textarea id={id} value={text} onChange={(e) => setText(e.target.value)} rows={3} className={inputClass} />
      </div>
      {answers.length > 0 && (
        <fieldset className="rounded-lg bg-surface-2 p-3 text-sm">
          <legend className="px-1 font-medium">Use facts from your answers (optional)</legend>
          {answers.map((a) => (
            <label key={a.id} className="mt-1 flex items-start gap-2">
              <input type="checkbox" className="mt-1" checked={cited.includes(a.id)}
                onChange={(e) => setCited(e.target.checked ? [...cited, a.id] : cited.filter((c) => c !== a.id))} />
              <span><code className="text-xs text-muted">{a.id}</code> {a.requirement}: <q>{a.answer}</q></span>
            </label>
          ))}
        </fieldset>
      )}
      {error && <Alert tone="bad" role="alert" title="Couldn't check that">{error}</Alert>}
      <div className="flex gap-2">
        <Button busy={saving} disabled={!text.trim()} onClick={async () => {
          setSaving(true);
          setError(null);
          try { await onSave(text.trim(), cited); } catch (e) { setError(messageFor(e)); } finally { setSaving(false); }
        }}>Save and re-check</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
      <p className="text-xs text-muted">We&apos;ll run the same honesty check on your edit before it can be approved.</p>
    </div>
  );
}
