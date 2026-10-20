/**
 * Review rules, kept out of components so they're easy to test.
 *
 * - "Flagged": the verifier raised anything (blocking or a warning).
 * - "Blocked": a blocking flag; it can never be approved, only rejected
 *   (keep original) or edited until it passes.
 * - Unchanged bullets need no decision: they export as written.
 * - Export requires every changed, flagged bullet (and a flagged summary) to have
 *   an explicit decision. Bulk approve never touches flagged bullets.
 */
import type { ReviewStatus, TailoredBullet, TailoredResume, VerificationFlag } from "./schemas";

export type Decisions = Record<string, ReviewStatus>;

export const isChanged = (b: TailoredBullet) => b.text.trim() !== b.original_text.trim();
export const isBlocked = (b: TailoredBullet) => !b.verification?.passed;
export const isFlagged = (b: TailoredBullet) => isBlocked(b) || (b.verification?.flags.length ?? 0) > 0;
export const decisionOf = (b: TailoredBullet, d: Decisions): ReviewStatus => d[b.id] ?? "pending";

/** Approving a blocked bullet is never allowed, wherever the request comes from. */
export function decide(d: Decisions, b: TailoredBullet, status: ReviewStatus): Decisions {
  if (status === "approved" && isBlocked(b)) return d;
  return { ...d, [b.id]: status };
}

export function approveAllVerified(t: TailoredResume, d: Decisions): Decisions {
  const next = { ...d };
  for (const b of t.bullets) {
    if (isChanged(b) && !isFlagged(b) && decisionOf(b, d) === "pending") next[b.id] = "approved";
  }
  return next;
}

export type ExportCheck = { ok: boolean; unresolved: string[]; summaryUnresolved: boolean };

export function exportCheck(t: TailoredResume, d: Decisions): ExportCheck {
  const unresolved = t.bullets
    .filter((b) => isChanged(b) && isFlagged(b))
    .filter((b) => {
      const s = decisionOf(b, d);
      return s === "pending" || (s === "approved" && isBlocked(b));
    })
    .map((b) => b.id);
  const summaryFlagged = !!t.summary && (t.summary_verification?.flags.length ?? 0) > 0;
  const summaryUnresolved = summaryFlagged && t.summary_review === "pending";
  return { ok: unresolved.length === 0 && !summaryUnresolved, unresolved, summaryUnresolved };
}

/** The tailored resume with the user's decisions applied, as the backend expects. */
export function withDecisions(t: TailoredResume, d: Decisions): TailoredResume {
  return { ...t, bullets: t.bullets.map((b) => ({ ...b, review: isChanged(b) ? decisionOf(b, d) : "pending" })) };
}

export type ReviewCounts = { changed: number; approved: number; rejected: number; pending: number; flagged: number };

export function counts(t: TailoredResume, d: Decisions): ReviewCounts {
  const changed = t.bullets.filter(isChanged);
  return {
    changed: changed.length,
    approved: changed.filter((b) => decisionOf(b, d) === "approved").length,
    rejected: changed.filter((b) => decisionOf(b, d) === "rejected").length,
    pending: changed.filter((b) => decisionOf(b, d) === "pending").length,
    flagged: changed.filter(isFlagged).length,
  };
}

const KIND_LABEL: Record<VerificationFlag["kind"], string> = {
  missing_source: "No source line",
  unknown_source: "Unknown source",
  cross_entry: "Mixes two jobs",
  new_tool: "New tool or skill",
  new_number: "New number",
  new_title: "New title",
  new_employer: "Different employer",
  inflated_verb: "Stronger claim",
  new_claim: "Wording to check",
};
export const flagLabel = (f: VerificationFlag) => KIND_LABEL[f.kind];

/** A short, honest explanation of what the tailor changed and why. */
export function whyThisChange(b: TailoredBullet, editedByYou = false): string {
  const parts: string[] = [];
  if (editedByYou) {
    parts.push("Edited by you, then re-checked against your original.");
    if (b.source_answer_ids.length) parts.push(`Uses what you told us (${b.source_answer_ids.join(", ")}).`);
    return parts.join(" ");
  }
  switch (b.change_type) {
    case "unchanged":
      parts.push(isChanged(b) ? "Edited by you." : "Kept exactly as you wrote it.");
      break;
    case "reorder":
      parts.push("Same words, moved up because it matches what the job asks for.");
      break;
    case "mirror_terminology":
      parts.push("Uses the job's spelling for something you already named, so ATS filters match it.");
      break;
    case "surface_metric":
      parts.push("Moves your existing number to the front, where a recruiter sees it first.");
      break;
    case "reword":
      parts.push("Reworded to lead with what this job cares about, keeping your facts.");
      break;
  }
  if (b.jd_terms_used.length) parts.push(`Job wording used: ${b.jd_terms_used.join(", ")}.`);
  if (b.source_answer_ids.length) parts.push(`Includes what you told us (${b.source_answer_ids.join(", ")}).`);
  return parts.join(" ");
}
