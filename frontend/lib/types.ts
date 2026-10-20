// Mirrors backend/app/models. Computed fields (passed, total, points, ...) come
// back from the API and are ignored by the backend when sent again.

export type SectionKind = "experience" | "projects" | "education" | "certifications" | "other";

export interface Bullet { id: string; text: string }

export interface Entry {
  id: string;
  title: string | null;
  organization: string | null;
  location: string | null;
  start_date: string | null;
  end_date: string | null;
  bullets: Bullet[];
}

export interface Section { kind: SectionKind; heading: string; entries: Entry[] }

export interface ParseWarning { code: string; message: string }

export interface Resume {
  name: string | null;
  contact: { email: string | null; phone: string | null; location: string | null; links: string[] };
  summary: string | null;
  skills: string[];
  sections: Section[];
  raw_text: string;
  parse_warnings: ParseWarning[];
}

export type Priority = "required" | "preferred";

export interface Requirement {
  id: string;
  text: string;
  priority: Priority;
  category: string;
  keywords: string[];
}

export interface JobDescription {
  title: string | null;
  company: string | null;
  seniority: string;
  years_experience_min: number | null;
  responsibilities: string[];
  requirements: Requirement[];
  raw_text: string;
}

export type GapStatus = "evidenced" | "implied" | "missing";
export type AnswerKind = "unanswered" | "confirmed" | "declined";

export interface ClarifyingQuestion {
  id: string;
  requirement_id: string;
  question: string;
  answer: string | null;
  answer_kind: AnswerKind;
}

export interface GapItem {
  requirement_id: string;
  requirement_text: string;
  priority: Priority;
  category: string;
  status: GapStatus;
  evidence_bullet_ids: string[];
  evidence_entry_ids: string[];
  evidence_skills: string[];
  matched_keywords: string[];
  missing_keywords: string[];
  rationale: string;
  question: ClarifyingQuestion | null;
  decided_by: string;
}

export interface GapAnalysis {
  items: GapItem[];
  candidate_years_experience: number | null;
  notes: string[];
  counts: Record<GapStatus, number>;
  required_coverage: number;
}

export type ChangeType = "unchanged" | "reorder" | "reword" | "mirror_terminology" | "surface_metric";
export type ReviewStatus = "pending" | "approved" | "rejected";

export interface VerificationFlag {
  kind: string;
  token: string;
  detail: string;
  severity: "block" | "warn";
}

export interface VerificationResult { flags: VerificationFlag[]; passed: boolean }

export interface TailoredBullet {
  id: string;
  text: string;
  source_bullet_ids: string[];
  source_answer_ids: string[];
  entry_id: string | null;
  original_text: string;
  change_type: ChangeType;
  jd_terms_used: string[];
  verification: VerificationResult | null;
  rejected_attempts: { text: string; flags: VerificationFlag[] }[];
  review: ReviewStatus;
}

export interface TailoredResume {
  entry_order: string[];
  bullets: TailoredBullet[];
  summary: string | null;
  summary_verification: VerificationResult | null;
  summary_review: ReviewStatus;
  notes: string[];
  blocked_rewrites: number;
}

export interface ScoreComponent {
  name: string;
  score: number;
  deterministic: boolean;
  matched: string[];
  missing: string[];
  notes: string;
  weight: number;
  points: number;
}

export interface ATSReport { components: ScoreComponent[]; disclaimer: string; total: number }

export interface ScoreResponse { before: ATSReport; after: ATSReport | null; delta: number | null }

export interface MentorAdvice {
  strengths: { text: string; evidence_bullet_ids: string[]; requirement_ids: string[] }[];
  gaps: {
    requirement_id: string | null;
    text: string;
    priority: Priority | null;
    status: GapStatus | null;
    severity: "critical" | "moderate" | "minor";
    why_it_matters: string;
  }[];
  actions: {
    id: string;
    kind: "answer_question" | "resume_edit" | "learn" | "apply_strategy";
    text: string;
    effort: string;
    requirement_ids: string[];
    bullet_ids: string[];
    question_id: string | null;
  }[];
  verdict: {
    decision: "strong_fit" | "apply" | "stretch" | "not_yet";
    headline: string;
    reasons: string[];
    caveat: string;
  };
  plan: {
    focus_skills: string[];
    hours_per_day: string;
    weeks: {
      week: number;
      focus: string;
      tasks: { id: string; days: string; title: string; detail: string; deliverable: string; requirement_ids: string[] }[];
    }[];
    not_addressable: string[];
  };
  notes: string[];
}
