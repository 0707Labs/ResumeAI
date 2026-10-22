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

/** POST /api/export/preview: the download, before paying, as watermarked low-res page
 * images rendered on the server (no resume text). */
export const ExportPreview = z.object({
  pages: z.array(z.object({
    image: z.string().startsWith("data:image/png;base64,"),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
  })),
  masked: z.array(z.string()),
  changed_count: z.number().int(),
  changed_marked: z.number().int(),
});

export const Health = z.object({ status: z.string(), llm_configured: z.boolean() });
export const Sample = z.object({ resume_text: z.string(), jd_text: z.string() });

// --- auth ------------------------------------------------------------------------------------------------

export const Me = z.object({
  id: z.uuid(),
  email: z.string(),
  name: z.string().nullable(),
  role: z.enum(["user", "support", "admin", "superadmin"]),
  status: z.enum(["active", "suspended"]),
  // What the UI may offer (app/auth/roles.py); strings, so a new backend capability can't
  // break parsing. The API checks again on every call.
  capabilities: z.array(z.string()),
  onboarded: z.boolean(),
  avatar_url: z.string().nullable(),  // same-origin /api/profile/avatar?v=...; null: initials
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
  /** Invite-only: a friend's referral link (rt_ref cookie) can be the invite. */
  has_referral_invite: z.boolean().default(false),
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
  redownload_free_days: z.number().int().default(7),
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
/** GET /api/referrals: your link and what it earned (friends are never named). */
const ReferralStatus = z.enum(["pending", "rewarded", "rejected"]);
export const Referrals = z.object({
  enabled: z.boolean(),
  code: z.string(),
  link: z.string(),
  trigger: z.enum(["on_verified_signup", "on_first_tailoring"]),
  reward_credits: z.number().int(),
  invitee_reward_credits: z.number().int(),
  monthly_cap: z.number().int(),
  rewarded_this_month: z.number().int(),
  invite_only: z.boolean(),
  invites_left: z.number().int(),
  total_earned: z.number().int(),
  pending: z.number().int(),
  rewarded: z.number().int(),
  referrals: z.array(z.object({
    id: z.uuid(),
    status: ReferralStatus,
    reason: z.string().nullable(),
    needs_review: z.boolean(),
    created_at: z.string(),
    rewarded_at: z.string().nullable(),
    credits: z.number().int(),
  })),
});
/** GET /api/referrals/updates: polled by the header. */
export const ReferralUpdates = z.object({
  credits_balance: z.number().int(),
  new_rewards: z.array(z.object({ id: z.uuid(), credits: z.number().int(), rewarded_at: z.string() })),
});
export const AdminReferrals = z.array(z.object({
  id: z.uuid(),
  referrer_email: z.string().nullable(),
  referee_email: z.string().nullable(),
  status: ReferralStatus,
  reason: z.string().nullable(),
  needs_review: z.boolean(),
  used_as_invite: z.boolean(),
  same_network: z.number().int(),
  reward_credits: z.number().int(),
  created_at: z.string(),
  rewarded_at: z.string().nullable(),
  reversed_at: z.string().nullable(),
}));
export type Referrals = z.infer<typeof Referrals>;
export type ReferralUpdates = z.infer<typeof ReferralUpdates>;
export type AdminReferrals = z.infer<typeof AdminReferrals>;
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

// --- user area (app/api/profile.py) ----------------------------------------------------------------

export const SENIORITY = ["intern", "junior", "mid", "senior", "lead", "principal"] as const;
export const WORK_MODES = ["remote", "hybrid", "onsite"] as const;
export const EMPLOYMENT_TYPES = ["full_time", "part_time", "contract", "internship", "freelance"] as const;

export const Preferences = z.object({
  target_roles: z.array(z.string()),
  seniority: z.enum(SENIORITY).nullable(),
  industries: z.array(z.string()),
  locations: z.array(z.string()),
  work_modes: z.array(z.enum(WORK_MODES)),
  employment_types: z.array(z.enum(EMPLOYMENT_TYPES)),
  notice_period_days: z.number().int().nullable(),
  updated_at: z.string().nullable(),
});
export type Preferences = z.infer<typeof Preferences>;
export type PreferencesIn = Omit<Preferences, "updated_at">;

export const ResumeSummary = z.object({
  id: z.uuid(),
  title: z.string(),
  is_default: z.boolean(),
  version: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type ResumeSummary = z.infer<typeof ResumeSummary>;

export const PlanStatus = z.object({
  kind: z.enum(["pass", "pro", "credits", "free"]),
  credits: z.number().int(),
  pass_expires_at: z.string().nullable(),
  pass_days_left: z.number().int().nullable(),
  pass_downloads_left: z.number().int().nullable(),
  pro_period_end: z.string().nullable(),
  free_allowance: z.number().int(),
  free_left: z.number().int(),
  resets_at: z.string(),
});
export type PlanStatus = z.infer<typeof PlanStatus>;

export const Dashboard = z.object({
  name: z.string().nullable(),
  plan: PlanStatus,
  recent: z.array(z.object({
    id: z.uuid(),
    job_title: z.string().nullable(),
    company: z.string().nullable(),
    created_at: z.string(),
    ats_before: z.number().nullable(),
    ats_after: z.number().nullable(),
    status: z.enum(["started", "tailored", "downloaded"]),
  })),
  last_tip: z.object({
    text: z.string(),
    job_title: z.string().nullable(),
    company: z.string().nullable(),
    created_at: z.string(),
  }).nullable(),
  referrals: z.object({
    enabled: z.boolean(),
    invites_per_user: z.number().int(),
    invites_left: z.number().int(),
    joined: z.number().int(),
    rewarded: z.number().int(),
    credits_earned: z.number().int(),
  }),
  has_resume: z.boolean(),
  has_preferences: z.boolean(),
});
export type Dashboard = z.infer<typeof Dashboard>;

export const Profile = z.object({
  name: z.string().nullable(),
  email: z.string(),
  phone: z.string().nullable(),
  avatar_url: z.string().nullable(),
  avatar_source: z.enum(["provider", "upload"]).nullable(),
});
export type Profile = z.infer<typeof Profile>;

const ResumeSource = z.enum(["upload", "paste", "edit"]);
export const ResumeDetail = ResumeSummary.extend({
  shown_version: z.number().int(),
  source: ResumeSource,
  resume: Resume,
});
export type ResumeDetail = z.infer<typeof ResumeDetail>;

export const VersionSummary = z.object({
  version: z.number().int(),
  source: ResumeSource,
  file_name: z.string().nullable(),
  created_at: z.string(),
});
export type VersionSummary = z.infer<typeof VersionSummary>;

export const TailoringSummary = z.object({
  id: z.uuid(),
  job_title: z.string().nullable(),
  company: z.string().nullable(),
  created_at: z.string(),
  ats_before: z.number().nullable(),
  ats_after: z.number().nullable(),
  status: z.enum(["started", "tailored", "downloaded"]),
  resume_id: z.uuid().nullable(),
  content_available: z.boolean(),
});
export type TailoringSummary = z.infer<typeof TailoringSummary>;
export const TailoringPage = z.object({ items: z.array(TailoringSummary), next_before: z.string().nullable() });
export type TailoringPage = z.infer<typeof TailoringPage>;
export const TailoringDetail = TailoringSummary.extend({
  resume: Resume.nullable(),
  jd: JobDescription.nullable(),
  tailored: TailoredResume.nullable(),
});
export type TailoringDetail = z.infer<typeof TailoringDetail>;

export const Consents = z.object({
  history: z.array(z.object({
    purpose: z.enum(["service", "research", "age_18_plus", "waitlist"]),
    action: z.enum(["granted", "withdrawn"]),
    method: z.string(),
    notice_version: z.string(),
    notice_url: z.string(),
    at: z.string(),
  })),
  research: z.boolean(),
  research_available: z.boolean(),
});
export type Consents = z.infer<typeof Consents>;

// --- invites, downloads history, support (app/api/invites.py, downloads.py, support.py) ----------

export const InviteStatus = z.enum(["sent", "expired", "revoked", "joined", "first_tailoring", "rewarded", "not_eligible"]);
export const Invites = z.object({
  limit: z.number().int(),
  used: z.number().int(),
  left: z.number().int(),
  enabled: z.boolean(),
  code: z.string(),
  link: z.string(),
  trigger: z.enum(["on_verified_signup", "on_first_tailoring"]),
  reward_credits: z.number().int(),
  credits_earned: z.number().int(),
  invitees: z.array(z.object({
    id: z.uuid(),
    via: z.enum(["email", "link"]),
    email: z.string(),
    status: InviteStatus,
    created_at: z.string(),
    expires_at: z.string().nullable(),
    can_revoke: z.boolean(),
  })),
});
export type Invites = z.infer<typeof Invites>;
export const InviteSent = z.object({ id: z.uuid(), email: z.string(), expires_at: z.string(), left: z.number().int() });

export const DownloadItem = z.object({
  id: z.uuid(),
  analysis_id: z.uuid(),
  file_name: z.string(),
  format: z.enum(["docx", "pdf"]),
  job_title: z.string().nullable(),
  company: z.string().nullable(),
  created_at: z.string(),
  paid_with: z.enum(["pass", "pro", "credit", "window"]),
  credits: z.number().int(),
  expires_at: z.string(),
  available: z.boolean(),
});
export type DownloadItem = z.infer<typeof DownloadItem>;
export const DownloadPage = z.object({ items: z.array(DownloadItem), next_before: z.string().nullable() });

export const TicketCategory = z.enum(["support", "feedback", "fabrication_report", "grievance", "billing", "privacy"]);
export const Ticket = z.object({
  id: z.uuid(),
  category: TicketCategory,
  subject: z.string(),
  status: z.enum(["open", "pending", "closed"]),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Ticket = z.infer<typeof Ticket>;

// --- admin console (app/api/admin_users.py, admin_invites.py, admin_support.py, admin.py) --------

const Role = z.enum(["user", "support", "admin", "superadmin"]);
export const AdminUserRow = z.object({
  id: z.uuid(), name: z.string().nullable(), email: z.string(), role: Role,
  status: z.enum(["active", "suspended", "deleted"]), plan: z.enum(["free", "credits", "pass", "pro"]),
  credits: z.number().int(), created_at: z.string(), last_active_at: z.string().nullable(),
  tailorings: z.number().int(), downloads: z.number().int(), referrals: z.number().int(), llm_cost_usd: z.number(),
});
export type AdminUserRow = z.infer<typeof AdminUserRow>;
const page = <T extends z.ZodType>(item: T) =>
  z.object({ items: z.array(item), total: z.number().int(), page: z.number().int(), page_size: z.number().int() });
export const AdminUserPage = page(AdminUserRow);
export type AdminUserPage = z.infer<typeof AdminUserPage>;
const Rec = z.record(z.string(), z.unknown());
export const AdminUserDetail = z.object({
  user: AdminUserRow, phone: z.string().nullable(), onboarded: z.boolean(), providers: z.array(Rec),
  plan: Rec.nullable(), ledger: z.array(Rec).nullable(), payments: z.array(Rec).nullable(),
  tailorings: z.array(Rec), downloads: z.array(Rec), invites_sent: z.array(Rec), invited_with: Rec.nullable(),
  referrals: z.array(Rec), referred_by: Rec.nullable(), tickets: z.array(Rec), audit: z.array(Rec),
  can: z.object({ users_write: z.boolean(), credits_adjust: z.boolean(), passes_grant: z.boolean(), users_delete: z.boolean() }),
});
export type AdminUserDetail = z.infer<typeof AdminUserDetail>;

export const AdminInviteRow = z.object({
  id: z.uuid(), code_hint: z.string(), kind: z.enum(["admin", "personal", "waitlist"]), campaign: z.string().nullable(),
  note: z.string().nullable(), email: z.string().nullable(), uses: z.number().int(), max_uses: z.number().int(),
  bonus_credits: z.number().int().nullable(), expires_at: z.string().nullable(), created_at: z.string(),
  created_by_email: z.string().nullable(), batch_id: z.uuid().nullable(),
  status: z.enum(["active", "exhausted", "expired", "revoked"]),
});
export type AdminInviteRow = z.infer<typeof AdminInviteRow>;
export const AdminInvitePage = page(AdminInviteRow);
export type AdminInvitePage = z.infer<typeof AdminInvitePage>;
export const GeneratedCodes = z.object({ batch_id: z.uuid(), codes: z.array(z.string()), expires_at: z.string().nullable() });
export type GeneratedCodes = z.infer<typeof GeneratedCodes>;
export const InviteFunnel = z.array(z.object({
  kind: z.enum(["admin", "personal", "waitlist"]), created: z.number().int(), redeemed: z.number().int(),
  first_tailoring: z.number().int(),
}));
export type InviteFunnel = z.infer<typeof InviteFunnel>;
export const WaitlistRow = z.object({
  id: z.uuid(), email: z.string(), source: z.string().nullable(),
  status: z.enum(["waiting", "invited", "converted", "rejected"]), created_at: z.string(), invited_at: z.string().nullable(),
});
export type WaitlistRow = z.infer<typeof WaitlistRow>;
export const WaitlistPage = page(WaitlistRow);
export type WaitlistPage = z.infer<typeof WaitlistPage>;
export const ApproveResult = z.object({ approved: z.number().int(), skipped: z.number().int(), failed: z.number().int() });

export const AdminTicketRow = z.object({
  id: z.uuid(), user_id: z.uuid().nullable(), email: z.string(), category: TicketCategory, subject: z.string(),
  status: z.enum(["open", "pending", "closed"]), assignee_id: z.uuid().nullable(), assignee_email: z.string().nullable(),
  analysis_id: z.uuid().nullable(), created_at: z.string(), updated_at: z.string(),
});
export type AdminTicketRow = z.infer<typeof AdminTicketRow>;
export const AdminTicketPage = page(AdminTicketRow);
export type AdminTicketPage = z.infer<typeof AdminTicketPage>;
export const TicketMessage = z.object({
  id: z.uuid(), kind: z.enum(["reply", "internal_note"]), body: z.string(), author_email: z.string().nullable(),
  emailed_at: z.string().nullable(), created_at: z.string(),
});
export type TicketMessage = z.infer<typeof TicketMessage>;
export const AdminTicketDetail = AdminTicketRow.extend({
  body: z.string(), messages: z.array(TicketMessage),
  staff: z.array(z.object({ id: z.uuid(), email: z.string(), role: Role })),
});
export type AdminTicketDetail = z.infer<typeof AdminTicketDetail>;

export const AdminSettings = z.object({
  values: z.object({
    invite_only: z.boolean(), analyses_paused: z.boolean(), maintenance_banner: z.string().nullable(),
    invites_per_user: z.number().int(), signup_bonus_credits: z.number().int(), referrals_enabled: z.boolean(),
    referral_trigger: z.enum(["on_verified_signup", "on_first_tailoring"]), referral_reward_credits: z.number().int(),
    referral_monthly_cap: z.number().int(), daily_budget_usd: z.number(), monthly_budget_usd: z.number(),
    budget_kill_switch: z.boolean(),
  }),
  overridden: z.array(z.string()),
  defaults: z.record(z.string(), z.unknown()),
});
export type AdminSettings = z.infer<typeof AdminSettings>;
export type SettingKey = keyof AdminSettings["values"];

// --- Admin revenue and costs (app/api/admin_money.py) ---

export const AdminRevenue = z.object({
  as_of: z.string().nullable(), days: z.number().int(),
  totals: z.object({
    gross_usd: z.number(), refunds_usd: z.number(), fees_usd: z.number(), net_usd: z.number(), net_after_fees_usd: z.number(),
    payments: z.number().int(), disputes: z.number().int(), unsettled: z.number().int(),
  }),
  fees_are_estimates: z.boolean(),
  by_product: z.array(z.object({ product_key: z.string(), kind: z.string(), payments: z.number().int(), gross_usd: z.number(),
    refunds_usd: z.number(), fees_usd: z.number(), net_usd: z.number() })),
  by_currency: z.array(z.object({ currency: z.string(), payments: z.number().int(), gross_minor: z.number().int(),
    refunded_minor: z.number().int() })),
  daily: z.array(z.object({ day: z.string(), gross_usd: z.number(), net_usd: z.number() })),
  subscriptions: z.object({ active: z.number().int(), by_status: z.record(z.string(), z.number().int()),
    cancelled_in_window: z.number().int(), churn_rate: z.number().nullable(), renewals_due_7d: z.number().int() }),
  referral_liability: z.object({ credits_granted_in_window: z.number().int(), credits_granted_total: z.number().int(),
    est_value_usd: z.number(), per_credit_usd: z.number() }),
});
export type AdminRevenue = z.infer<typeof AdminRevenue>;

export const AdminPaymentRow = z.object({
  id: z.uuid(), user_id: z.uuid().nullable(), user_email: z.string().nullable(), product_key: z.string(), kind: z.string(),
  status: z.string(), mode: z.string(), currency: z.string().nullable(), amount_minor: z.number().int().nullable(),
  refunded_amount_minor: z.number().int(), provider_payment_id: z.string().nullable(), disputed: z.boolean(),
  created_at: z.string(), paid_at: z.string().nullable(),
});
export type AdminPaymentRow = z.infer<typeof AdminPaymentRow>;
export const AdminPaymentPage = page(AdminPaymentRow);
export const RefundResult = z.object({ provider_refund_id: z.string().nullable(), status: z.string().nullable() });

const CostGroup = z.array(z.object({ key: z.string(), cost_usd: z.number(), calls: z.number().int() }));
export const AdminCosts = z.object({
  as_of: z.string().nullable(), days: z.number().int(), granularity: z.enum(["day", "week", "month"]),
  total_usd: z.number(), calls: z.number().int(), failed_calls: z.number().int(), error_rate: z.number().nullable(),
  wasted_usd: z.number(), unpriced_calls: z.number().int(), free_tier_usd: z.number(),
  series: z.array(z.object({ period: z.string(), cost_usd: z.number(), calls: z.number().int() })),
  by_step: CostGroup, by_model: CostGroup, by_plan: CostGroup,
  per_analysis: z.object({ analyses: z.number().int(), avg_usd: z.number().nullable(), p95_usd: z.number().nullable() }),
  top_users: z.array(z.object({ user_id: z.uuid(), email: z.string(), cost_usd: z.number(), calls: z.number().int() })),
  margin: z.object({ net_revenue_usd: z.number(), analyses: z.number().int(), cost_usd: z.number(),
    revenue_per_analysis_usd: z.number().nullable(), cost_per_analysis_usd: z.number().nullable() }),
  budget: z.object({ today_usd: z.number(), month_usd: z.number(), daily_budget_usd: z.number(), monthly_budget_usd: z.number(),
    kill_switch: z.boolean(), paused: z.enum(["manual", "daily_budget", "monthly_budget"]).nullable(), analyses_paused: z.boolean() }),
  per_user_daily_caps: z.object({ free: z.number().int().nullable(), paid: z.number().int().nullable() }),
  prices: z.array(z.object({ model: z.string(), input: z.number(), output: z.number(), cache_read: z.number().nullable(),
    cache_write: z.number().nullable() })),
});
export type AdminCosts = z.infer<typeof AdminCosts>;
