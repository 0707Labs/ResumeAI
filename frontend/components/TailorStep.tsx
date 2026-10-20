"use client";

import { useState } from "react";

import { wordDiff } from "@/lib/diff";
import type { Resume, ReviewStatus, TailoredBullet, TailoredResume, VerificationFlag } from "@/lib/types";

import { Button, Card, Empty, Note, Pill } from "./ui";

const CHANGE_LABEL: Record<TailoredBullet["change_type"], string> = {
  unchanged: "unchanged",
  reorder: "moved",
  reword: "reworded",
  mirror_terminology: "JD wording",
  surface_metric: "metric first",
};

export type ConfirmedAnswer = { id: string; requirement: string; answer: string };

export function TailorStep({ resume, tailored, answers, busy, ready, onTailor, onReview, onEdit, onSummaryReview, onApproveAll, onExport }: {
  resume: Resume | null;
  answers: ConfirmedAnswer[];
  tailored: TailoredResume | null;
  busy: boolean;
  ready: boolean;
  onTailor: () => void;
  onReview: (id: string, review: ReviewStatus) => void;
  onEdit: (id: string, text: string, answerIds: string[]) => Promise<void>;
  onSummaryReview: (review: ReviewStatus) => void;
  onApproveAll: () => void;
  onExport: (fmt: "docx" | "pdf") => void;
}) {
  const entries = resume?.sections.flatMap((s) => s.entries) ?? [];
  const counts = tailored
    ? {
        approved: tailored.bullets.filter((b) => b.review === "approved").length,
        rejected: tailored.bullets.filter((b) => b.review === "rejected").length,
        blocked: tailored.bullets.filter((b) => !b.verification?.passed).length,
      }
    : null;

  return (
    <div className="space-y-5">
      <Card title="4. Tailor and review" actions={
        <Button onClick={onTailor} busy={busy && !tailored} disabled={!ready}>{tailored ? "Re-tailor" : "Tailor bullets"}</Button>
      }>
        {!ready && <Empty>Run the gap analysis first. Your confirmed answers feed tailoring.</Empty>}
        {tailored && counts && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Pill tone="green">{counts.approved} approved</Pill>
              <Pill tone="rose">{counts.rejected} rejected</Pill>
              <Pill>{tailored.bullets.length - counts.approved - counts.rejected} pending</Pill>
              {tailored.blocked_rewrites > 0 && <Pill tone="amber">{tailored.blocked_rewrites} rewrite(s) blocked by verifier</Pill>}
              <span className="flex-1" />
              <Button variant="secondary" onClick={onApproveAll}>Approve all that pass</Button>
            </div>
            {tailored.notes.map((n) => <Note key={n}>{n}</Note>)}
          </div>
        )}
      </Card>

      {tailored?.summary && (
        <Card title="Summary" actions={<ReviewButtons review={tailored.summary_review} onReview={onSummaryReview} disabled={!tailored.summary_verification?.passed} />}>
          {resume?.summary && <Diff before={resume.summary} after={tailored.summary} />}
          {!resume?.summary && <p className="text-sm text-slate-800">{tailored.summary}</p>}
          <Flags flags={tailored.summary_verification?.flags ?? []} />
        </Card>
      )}

      {tailored && entries.filter((e) => tailored.bullets.some((b) => b.entry_id === e.id)).map((e) => (
        <Card key={e.id} title={
          <>{[e.title, e.organization].filter(Boolean).join(" — ") || e.id}
            <span className="ml-2 text-sm font-normal text-slate-500">{[e.start_date, e.end_date].filter(Boolean).join(" – ")}</span></>
        }>
          <ul className="space-y-3">
            {tailored.bullets.filter((b) => b.entry_id === e.id).map((b) => (
              <BulletRow key={b.id} bullet={b} answers={answers} onReview={onReview} onEdit={onEdit} />
            ))}
          </ul>
        </Card>
      ))}

      {tailored && (
        <Card title="Export" actions={<>
          <Button variant="secondary" onClick={() => onExport("docx")}>Download DOCX</Button>
          <Button variant="secondary" onClick={() => onExport("pdf")}>Download PDF</Button>
        </>}>
          <Note>
            Only bullets you approved, and that pass verification again on the server, use the tailored wording.
            Everything else exports exactly as in your original resume. The layout is single-column with no tables,
            which ATS parsers handle best.
          </Note>
        </Card>
      )}
    </div>
  );
}

function BulletRow({ bullet, answers, onReview, onEdit }: {
  bullet: TailoredBullet;
  answers: ConfirmedAnswer[];
  onReview: (id: string, review: ReviewStatus) => void;
  onEdit: (id: string, text: string, answerIds: string[]) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(bullet.text);
  const [cited, setCited] = useState<string[]>(bullet.source_answer_ids);
  const [saving, setSaving] = useState(false);
  const passed = bullet.verification?.passed ?? false;
  const border = bullet.review === "approved" ? "border-emerald-300 bg-emerald-50/40"
    : bullet.review === "rejected" ? "border-slate-200 bg-slate-50 opacity-60"
    : !passed ? "border-rose-300 bg-rose-50/40" : "border-slate-200";

  return (
    <li className={`rounded-lg border p-3 ${border}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Pill tone={passed ? "green" : "rose"}>{passed ? "verified" : "blocked"}</Pill>
        <Pill tone="blue">{CHANGE_LABEL[bullet.change_type]}</Pill>
        <code className="text-xs text-slate-400">from {bullet.source_bullet_ids.join(", ") || "—"}
          {bullet.source_answer_ids.length > 0 && ` + answer ${bullet.source_answer_ids.join(", ")}`}</code>
        <span className="flex-1" />
        {!editing && <Button variant="ghost" onClick={() => { setDraft(bullet.text); setCited(bullet.source_answer_ids); setEditing(true); }}>Edit</Button>}
        <ReviewButtons review={bullet.review} onReview={(r) => onReview(bullet.id, r)} disabled={!passed} />
      </div>

      {editing ? (
        <div className="space-y-2">
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={2}
            className="w-full rounded-md border border-slate-300 p-2 text-sm focus:border-slate-900 focus:outline-none" />
          {answers.length > 0 && (
            <fieldset className="rounded-md bg-slate-50 p-2 text-xs text-slate-700">
              <legend className="px-1 font-medium">Cite your confirmed answers (lets this bullet use facts from them)</legend>
              {answers.map((a) => (
                <label key={a.id} className="mt-1 flex items-start gap-2">
                  <input type="checkbox" checked={cited.includes(a.id)}
                    onChange={(e) => setCited(e.target.checked ? [...cited, a.id] : cited.filter((c) => c !== a.id))} />
                  <span><code className="text-slate-400">{a.id}</code> {a.requirement}: <i>&ldquo;{a.answer}&rdquo;</i></span>
                </label>
              ))}
            </fieldset>
          )}
          <div className="flex gap-2">
            <Button busy={saving} onClick={async () => {
              setSaving(true);
              try { await onEdit(bullet.id, draft, cited); setEditing(false); } finally { setSaving(false); }
            }}>Save and re-check</Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </div>
      ) : (
        <Diff before={bullet.original_text} after={bullet.text} />
      )}

      <Flags flags={bullet.verification?.flags ?? []} />

      {bullet.rejected_attempts.length > 0 && (
        <details className="mt-2 text-xs text-slate-600">
          <summary className="cursor-pointer select-none text-amber-700">
            {bullet.rejected_attempts.length} rewrite(s) refused by the verifier
          </summary>
          <ul className="mt-2 space-y-2">
            {bullet.rejected_attempts.map((a, i) => (
              <li key={i} className="rounded bg-amber-50 p-2">
                <p className="line-through decoration-rose-400">{a.text}</p>
                <ul className="mt-1 list-disc pl-4">
                  {a.flags.filter((f) => f.severity === "block").map((f, j) => <li key={j}>{f.detail}</li>)}
                </ul>
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

function ReviewButtons({ review, onReview, disabled }: {
  review: ReviewStatus;
  onReview: (r: ReviewStatus) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex gap-1.5">
      <Button variant={review === "approved" ? "success" : "secondary"} disabled={disabled}
        title={disabled ? "Blocked by the verifier; edit it or keep the original" : "Use this wording"}
        onClick={() => onReview(review === "approved" ? "pending" : "approved")}>
        {review === "approved" ? "✓ Approved" : "Approve"}
      </Button>
      <Button variant="danger" onClick={() => onReview(review === "rejected" ? "pending" : "rejected")}>
        {review === "rejected" ? "Rejected" : "Reject"}
      </Button>
    </div>
  );
}

function Diff({ before, after }: { before: string; after: string }) {
  if (before === after) return <p className="text-sm text-slate-800">{after}</p>;
  return (
    <p className="text-sm leading-relaxed text-slate-800">
      {wordDiff(before, after).map((p, i) => (
        <span key={i} className={p.type === "added" ? "diff-added" : p.type === "removed" ? "diff-removed" : ""}>{p.text}</span>
      ))}
    </p>
  );
}

function Flags({ flags }: { flags: VerificationFlag[] }) {
  if (!flags.length) return null;
  return (
    <ul className="mt-2 space-y-1">
      {flags.map((f, i) => (
        <li key={i} className={`text-xs ${f.severity === "block" ? "text-rose-700" : "text-amber-700"}`}>
          {f.severity === "block" ? "⛔" : "⚠"} <b>{f.kind.replace(/_/g, " ")}</b>: {f.detail}
          {f.severity === "warn" && f.token && <span className="text-amber-900"> ({f.token})</span>}
        </li>
      ))}
    </ul>
  );
}
