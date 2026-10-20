/**
 * Zod schemas mirroring backend/app/models (pydantic). Types are inferred from
 * these, so the runtime check and the static type can't drift apart.
 *
 * Objects are non-strict on purpose: if the backend adds a field, older UI keeps
 * working. A missing or wrong-typed field fails loudly instead.
 * Computed fields (passed, total, points, ...) come from the backend; it ignores
 * them when they're sent back.
 */
import { z } from "zod";

// --- resume ---------------------------------------------------------------------------

export const SectionKind = z.enum(["experience", "projects", "education", "certifications", "other"]);

export const Bullet = z.object({ id: z.string(), text: z.string() });

export const Entry = z.object({
  id: z.string(),
  title: z.string().nullable(),
  organization: z.string().nullable(),
  location: z.string().nullable(),
  start_date: z.string().nullable(),
  end_date: z.string().nullable(),
  bullets: z.array(Bullet),
});

export const Section = z.object({ kind: SectionKind, heading: z.string(), entries: z.array(Entry) });

export const ParseWarningCode = z.enum([
  "tables_detected",
  "images_detected",
  "multi_column_suspected",
  "no_sections_found",
  "no_bullets_found",
  "contact_missing",
  "name_not_found",
]);

export const ParseWarning = z.object({ code: ParseWarningCode, message: z.string() });

export const Resume = z.object({
  name: z.string().nullable(),
  contact: z.object({
    email: z.string().nullable(),
    phone: z.string().nullable(),
    location: z.string().nullable(),
    links: z.array(z.string()),
  }),
  summary: z.string().nullable(),
  skills: z.array(z.string()),
  sections: z.array(Section),
  raw_text: z.string(),
  parse_warnings: z.array(ParseWarning),
});

// --- job description ----------------------------------------------------------------------

export const Priority = z.enum(["required", "preferred"]);
export const RequirementCategory = z.enum(["skill", "experience", "education", "certification", "other"]);
export const Seniority = z.enum(["intern", "junior", "mid", "senior", "lead", "principal", "unknown"]);

export const Requirement = z.object({
  id: z.string(),
  text: z.string(),
  priority: Priority,
  category: RequirementCategory,
  keywords: z.array(z.string()),
});

export const JobDescription = z.object({
  title: z.string().nullable(),
  company: z.string().nullable(),
  seniority: Seniority,
  years_experience_min: z.number().nullable(),
  responsibilities: z.array(z.string()),
  requirements: z.array(Requirement),
  raw_text: z.string(),
});

// --- gap analysis ---------------------------------------------------------------------------

export const GapStatus = z.enum(["evidenced", "implied", "missing"]);
export const AnswerKind = z.enum(["unanswered", "confirmed", "declined"]);

export const ClarifyingQuestion = z.object({
  id: z.string(),
  requirement_id: z.string(),
  question: z.string(),
  answer: z.string().nullable(),
  answer_choice: z.enum(["yes", "no"]).nullable(),
  answer_kind: AnswerKind,
});

export const GapItem = z.object({
  requirement_id: z.string(),
  requirement_text: z.string(),
  priority: Priority,
  category: RequirementCategory,
  status: GapStatus,
  evidence_bullet_ids: z.array(z.string()),
  evidence_entry_ids: z.array(z.string()),
  evidence_skills: z.array(z.string()),
  matched_keywords: z.array(z.string()),
  missing_keywords: z.array(z.string()),
  rationale: z.string(),
  question: ClarifyingQuestion.nullable(),
  decided_by: z.string(),
});

export const GapAnalysis = z.object({
  items: z.array(GapItem),
  candidate_years_experience: z.number().nullable(),
  notes: z.array(z.string()),
  counts: z.record(GapStatus, z.number()),
  required_coverage: z.number(),
});

// --- tailoring + verification -----------------------------------------------------------------

export const ChangeType = z.enum(["unchanged", "reorder", "reword", "mirror_terminology", "surface_metric"]);
export const ReviewStatus = z.enum(["pending", "approved", "rejected"]);
export const FlagKind = z.enum([
  "missing_source",
  "unknown_source",
  "cross_entry",
  "new_tool",
  "new_number",
  "new_title",
  "new_employer",
  "inflated_verb",
  "new_claim",
]);

export const VerificationFlag = z.object({
  kind: FlagKind,
  token: z.string(),
  detail: z.string(),
  severity: z.enum(["block", "warn"]),
});

export const VerificationResult = z.object({ flags: z.array(VerificationFlag), passed: z.boolean() });

export const RejectedAttempt = z.object({ text: z.string(), flags: z.array(VerificationFlag) });

export const TailoredBullet = z.object({
  id: z.string(),
  text: z.string(),
  source_bullet_ids: z.array(z.string()),
  source_answer_ids: z.array(z.string()),
  entry_id: z.string().nullable(),
  original_text: z.string(),
  change_type: ChangeType,
  jd_terms_used: z.array(z.string()),
  verification: VerificationResult.nullable(),
  rejected_attempts: z.array(RejectedAttempt),
  review: ReviewStatus,
});

export const TailoredResume = z.object({
  entry_order: z.array(z.string()),
  bullets: z.array(TailoredBullet),
  summary: z.string().nullable(),
  summary_verification: VerificationResult.nullable(),
  summary_review: ReviewStatus,
  notes: z.array(z.string()),
  blocked_rewrites: z.number(),
});

export const VerifyResponse = z.object({
  bullets: z.array(TailoredBullet),
  summary_verification: VerificationResult.nullable(),
});

// --- ATS score ------------------------------------------------------------------------------------

export const ComponentName = z.enum([
  "required_keywords",
  "preferred_keywords",
  "semantic_relevance",
  "title_seniority",
  "format_parseability",
  "quantified_impact",
]);

export const ScoreComponent = z.object({
  name: ComponentName,
  score: z.number(),
  deterministic: z.boolean(),
  matched: z.array(z.string()),
  missing: z.array(z.string()),
  notes: z.string(),
  weight: z.number(),
  points: z.number(),
});

export const ATSReport = z.object({
  components: z.array(ScoreComponent),
  disclaimer: z.string(),
  total: z.number(),
});

export const ScoreResponse = z.object({
  before: ATSReport,
  after: ATSReport.nullable(),
  delta: z.number().nullable(),
});

// --- mentor ------------------------------------------------------------------------------------------

export const GapSeverity = z.enum(["critical", "moderate", "minor"]);
export const ActionKind = z.enum(["answer_question", "resume_edit", "learn", "apply_strategy"]);
export const Decision = z.enum(["strong_fit", "apply", "stretch", "not_yet"]);

export const MentorAdvice = z.object({
  strengths: z.array(z.object({
    text: z.string(),
    evidence_bullet_ids: z.array(z.string()),
    requirement_ids: z.array(z.string()),
  })),
  gaps: z.array(z.object({
    requirement_id: z.string().nullable(),
    text: z.string(),
    priority: Priority.nullable(),
    status: GapStatus.nullable(),
    severity: GapSeverity,
    why_it_matters: z.string(),
  })),
  actions: z.array(z.object({
    id: z.string(),
    kind: ActionKind,
    text: z.string(),
    effort: z.string(),
    requirement_ids: z.array(z.string()),
    bullet_ids: z.array(z.string()),
    question_id: z.string().nullable(),
  })),
  verdict: z.object({
    decision: Decision,
    headline: z.string(),
    reasons: z.array(z.string()),
    caveat: z.string(),
  }),
  plan: z.object({
    focus_skills: z.array(z.string()),
    hours_per_day: z.string(),
    weeks: z.array(z.object({
      week: z.number(),
      focus: z.string(),
      tasks: z.array(z.object({
        id: z.string(),
        days: z.string(),
        title: z.string(),
        detail: z.string(),
        deliverable: z.string(),
        requirement_ids: z.array(z.string()),
      })),
    })),
    not_addressable: z.array(z.string()),
  }),
  talking_points: z.array(z.object({
    id: z.string(),
    kind: z.enum(["strength", "answer", "gap"]),
    prompt: z.string(),
    detail: z.string(),
    bullet_ids: z.array(z.string()),
    requirement_ids: z.array(z.string()),
  })),
  notes: z.array(z.string()),
});

export const ExportPreview = z.object({
  resume: Resume, // exactly what the downloaded file will contain
  changed_lines: z.array(z.string()),
});

export const Health = z.object({ status: z.string(), llm_configured: z.boolean() });
export const Sample = z.object({ resume_text: z.string(), jd_text: z.string() });

// --- auth ------------------------------------------------------------------------------------------------

export const Me = z.object({
  id: z.uuid(),
  email: z.string(),
  name: z.string().nullable(),
  role: z.enum(["user", "admin"]),
  status: z.enum(["active", "suspended"]),
});
export const CsrfToken = z.object({ csrf_token: z.string().min(1) });

const Provider = z.enum(["google", "github", "email"]);
export const ProviderAvailability = z.object({ google: z.boolean(), github: z.boolean(), email: z.boolean() });
/** Where the auth flow goes next (backend AuthStep). */
export const AuthStep = z.object({ next: z.enum(["signed_in", "invite", "consent", "verify_email", "linked"]) });
export const Accepted = z.object({ status: z.literal("ok") });
export const PendingSignIn = z.object({
  kind: z.enum(["signup", "needs_email"]),
  provider: Provider,
  email: z.string().nullable(),
  invite_accepted: z.boolean(),
  has_bound_invite: z.boolean(),
});
export const Notice = z.object({
  id: z.uuid(),
  purpose: z.enum(["service", "research", "age_18_plus", "waitlist"]),
  version: z.string(),
  body_url: z.string(),
});
export const Notices = z.array(Notice);
export const LinkedAccount = z.object({ id: z.uuid(), provider: Provider, email: z.string(), linked_at: z.string() });
export const AccountProviders = z.object({
  accounts: z.array(LinkedAccount),
  can_unlink: z.boolean(),
  available: z.object({ google: z.boolean(), github: z.boolean(), email: z.boolean() }),
});

// --- inferred types ------------------------------------------------------------------------------------

export type Resume = z.infer<typeof Resume>;
export type Entry = z.infer<typeof Entry>;
export type ParseWarning = z.infer<typeof ParseWarning>;
export type JobDescription = z.infer<typeof JobDescription>;
export type Requirement = z.infer<typeof Requirement>;
export type GapStatus = z.infer<typeof GapStatus>;
export type GapItem = z.infer<typeof GapItem>;
export type GapAnalysis = z.infer<typeof GapAnalysis>;
export type ClarifyingQuestion = z.infer<typeof ClarifyingQuestion>;
export type ReviewStatus = z.infer<typeof ReviewStatus>;
export type VerificationFlag = z.infer<typeof VerificationFlag>;
export type VerificationResult = z.infer<typeof VerificationResult>;
export type TailoredBullet = z.infer<typeof TailoredBullet>;
export type TailoredResume = z.infer<typeof TailoredResume>;
export type ScoreComponent = z.infer<typeof ScoreComponent>;
export type ATSReport = z.infer<typeof ATSReport>;
export type ScoreResponse = z.infer<typeof ScoreResponse>;
export type MentorAdvice = z.infer<typeof MentorAdvice>;
export type ExportPreview = z.infer<typeof ExportPreview>;
export type Me = z.infer<typeof Me>;
export type ProviderAvailability = z.infer<typeof ProviderAvailability>;
export type AuthStep = z.infer<typeof AuthStep>;
export type PendingSignIn = z.infer<typeof PendingSignIn>;
export type Notice = z.infer<typeof Notice>;
export type LinkedAccount = z.infer<typeof LinkedAccount>;
export type AccountProviders = z.infer<typeof AccountProviders>;
