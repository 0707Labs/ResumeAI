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

/** GET /api/analyses/allowance: free tailorings left this month and what the next run uses. */
export const Allowance = z.object({
  free_allowance: z.number().int(),
  free_used: z.number().int(),
  resets_at: z.string(),
  next_uses: z.enum(["pass", "pro", "credit", "free"]).nullable(),
  credits_balance: z.number().int(),
});
/** POST /api/analyses: a started analysis (spends nothing; the download pays). */
export const AnalysisStarted = z.object({
  analysis_id: z.uuid(),
  usable_until: z.string(),
  uses: z.enum(["pass", "pro", "credit", "free"]).nullable(),
  // false: started over the daily Claude cap, so this analysis runs rules-only.
  claude: z.boolean().default(true),
  claude_per_day: z.number().int().nonnegative().optional(),
});
/** POST /api/downloads/{fmt}: a paid download's short-lived signed link. */
export const DownloadLink = z.object({
  url: z.string().startsWith("/api/downloads/file/"),
  expires_at: z.string(),
  paid_with: z.enum(["pass", "pro", "credit", "window"]),
  credits_balance: z.number().int(),
});

const Provider = z.enum(["google", "github", "email"]);
export const ProviderAvailability = z.object({ google: z.boolean(), github: z.boolean(), email: z.boolean() });
/** Where the auth flow goes next (backend AuthStep). */
export const AuthStep = z.object({ next: z.enum(["signed_in", "invite", "consent", "verify_email", "linked"]) });
export const Accepted = z.object({ status: z.literal("ok") });
/** Flags the signed-out pages need (GET /api/auth/config). */
export const PublicConfig = z.object({ invite_only: z.boolean() });
export const PendingSignIn = z.object({
  kind: z.enum(["signup", "needs_email"]),
  provider: Provider,
  email: z.string().nullable(),
  /** False when signup is open (RT_INVITE_ONLY off): the invite step is skipped. */
  invite_required: z.boolean(),
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

// --- billing (backend app/api/billing.py) ---------------------------------------------------------------

const Money = z.record(z.string(), z.number().int().positive());
export const Plan = z.object({
  key: z.string(),
  kind: z.enum(["credit_pack", "pass", "subscription"]),
  name: z.string(),
  prices: Money,
  credits: z.number().int().nullable(),
  pass_days: z.number().int().nullable(),
  fair_use_cap: z.number().int().nullable(),
  interval: z.string().nullable(),
  available: z.boolean(),
});
export const Plans = z.object({
  free_analyses_per_month: z.number().int(),
  prices_include_tax: z.boolean(),
  plans: z.array(Plan),
});
export const CheckoutStarted = z.object({ payment_id: z.uuid(), checkout_url: z.url({ protocol: /^https$/ }) });
export const PaymentStatus = z.object({
  id: z.uuid(),
  product_key: z.string(),
  kind: z.string(),
  status: z.enum(["created", "checkout_failed", "pending", "paid", "failed", "cancelled",
    "partially_refunded", "refunded", "disputed"]),
  credits_balance: z.number().int(),
});
export const BillingSummary = z.object({
  credits_balance: z.number().int(),
  passes: z.array(z.object({
    product_key: z.string(),
    starts_at: z.string(),
    expires_at: z.string(),
    days_remaining: z.number().int(),
    analyses_cap: z.number().int(),
  })),
  subscription: z.object({
    product_key: z.string(),
    status: z.string(),
    current_period_end: z.string().nullable(),
    cancel_at_period_end: z.boolean(),
  }).nullable(),
  purchases: z.array(z.object({
    id: z.uuid(),
    product_key: z.string(),
    name: z.string(),
    status: z.string(),
    amount_minor: z.number().int().nullable(),
    currency: z.string().nullable(),
    created_at: z.string(),
    paid_at: z.string().nullable(),
  })),
  portal_available: z.boolean(),
});
export const LedgerPage = z.object({
  entries: z.array(z.object({
    id: z.number().int(),
    delta: z.number().int(),
    reason: z.string(),
    balance_after: z.number().int(),
    created_at: z.string(),
  })),
  next_before: z.number().int().nullable(),
});
export const PortalLink = z.object({ url: z.url({ protocol: /^https$/ }) });

const AdminAlert = z.object({ kind: z.string(), severity: z.enum(["critical", "warning"]), message: z.string() });
export const AdminOverview = z.object({
  days: z.number().int(),
  payment_counts: z.record(z.string(), z.number().int()),
  payments: z.array(z.object({
    id: z.uuid(),
    email: z.string().nullable(),
    product_key: z.string(),
    status: z.string(),
    amount_minor: z.number().int().nullable(),
    currency: z.string().nullable(),
    refunded_amount_minor: z.number().int(),
    provider_payment_id: z.string().nullable(),
    created_at: z.string(),
    paid_at: z.string().nullable(),
  })),
  credits: z.object({ sold: z.number(), consumed: z.number(), reversed: z.number(), outstanding: z.number() }),
  llm: z.object({
    calls: z.number().int(),
    total_cost_usd: z.number(),
    analyses: z.number().int(),
    avg_cost_per_analysis_usd: z.number().nullable(),
    unpriced_calls: z.number().int(),
    by_model: z.array(z.object({ model: z.string(), calls: z.number().int(), cost_usd: z.number() })),
    daily: z.array(z.object({ day: z.string(), cost_usd: z.number() })),
  }),
  margin: z.array(z.object({
    product_key: z.string(),
    units: z.number().int(),
    settled_usd_cents: z.number().int(),
    refunded_usd_cents: z.number().int(),
    fees_usd_cents: z.number().int(),
    net_usd_cents: z.number().int(),
    other_currency_units: z.number().int(),
    runs_if_fully_used: z.number().int(),
    llm_cost_if_fully_used_usd_cents: z.number().int().nullable(),
    margin_if_fully_used_usd_cents: z.number().int().nullable(),
  })),
  fees_are_estimates: z.boolean(),
  reviews: z.array(z.object({
    id: z.uuid(),
    kind: z.string(),
    payment_id: z.uuid().nullable(),
    detail: z.record(z.string(), z.unknown()),
    created_at: z.string(),
  })),
  failing_webhooks: z.array(z.object({
    event_id: z.string(),
    event_type: z.string(),
    failures: z.number().int(),
    last_error: z.string().nullable(),
    received_at: z.string(),
  })),
  alerts: z.array(AdminAlert),
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
export type DownloadLink = z.infer<typeof DownloadLink>;
export type Allowance = z.infer<typeof Allowance>;
export type PublicConfig = z.infer<typeof PublicConfig>;
export type Notice = z.infer<typeof Notice>;
export type LinkedAccount = z.infer<typeof LinkedAccount>;
export type AccountProviders = z.infer<typeof AccountProviders>;
export type Plan = z.infer<typeof Plan>;
export type Plans = z.infer<typeof Plans>;
export type PaymentStatus = z.infer<typeof PaymentStatus>;
export type BillingSummary = z.infer<typeof BillingSummary>;
export type LedgerPage = z.infer<typeof LedgerPage>;
export type AdminOverview = z.infer<typeof AdminOverview>;
