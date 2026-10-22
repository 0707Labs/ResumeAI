/**
 * The signed-in user area (backend app/api/profile.py). Same rules as auth.ts: our origin
 * only, CSRF on writes, every response validated with its zod schema.
 */
import { AuthError, call } from "./auth";
import * as S from "./schemas";

export const userApi = {
  dashboard: () => call(S.Dashboard, "/api/dashboard"),
  plan: () => call(S.PlanStatus, "/api/plan"),
  setName: (name: string) => call(null, "/api/profile", { method: "PATCH", body: { name } }),
  finishOnboarding: () => call(null, "/api/profile/onboarded", { method: "POST" }),
  preferences: () => call(S.Preferences, "/api/profile/preferences"),
  savePreferences: (body: S.PreferencesIn) => call(S.Preferences, "/api/profile/preferences", { method: "PUT", body }),
  resumes: () => call(S.ResumeSummary.array(), "/api/resumes"),
  saveResume: (body: { resume: S.Resume; source: "upload" | "paste"; file_name?: string; title?: string }) =>
    call(S.ResumeSummary, "/api/resumes", { method: "POST", body }),
};

export const SENIORITY_LABEL: Record<(typeof S.SENIORITY)[number], string> = {
  intern: "Intern", junior: "Junior", mid: "Mid-level", senior: "Senior", lead: "Lead", principal: "Principal",
};
export const WORK_MODE_LABEL: Record<(typeof S.WORK_MODES)[number], string> = {
  remote: "Remote", hybrid: "Hybrid", onsite: "On-site",
};
export const EMPLOYMENT_LABEL: Record<(typeof S.EMPLOYMENT_TYPES)[number], string> = {
  full_time: "Full-time", part_time: "Part-time", contract: "Contract", internship: "Internship", freelance: "Freelance",
};
export const NOTICE_OPTIONS: { value: number | null; label: string }[] = [
  { value: null, label: "Prefer not to say" }, { value: 0, label: "Immediately" }, { value: 15, label: "15 days" },
  { value: 30, label: "30 days" }, { value: 60, label: "60 days" }, { value: 90, label: "90 days" },
];

/** "Pass · 12 days left", "Pro", "3 credits", "Free · 1 of 2 left". */
export function planLabel(plan: S.PlanStatus): string {
  if (plan.kind === "pass") return `Pass · ${plan.pass_days_left} day${plan.pass_days_left === 1 ? "" : "s"} left`;
  if (plan.kind === "pro") return "Pro";
  if (plan.kind === "credits") return `${plan.credits} credit${plan.credits === 1 ? "" : "s"}`;
  return `Free · ${plan.free_left} of ${plan.free_allowance} left`;
}

/** Initials for the avatar: from the name, else the email. */
export function initials(name: string | null, email: string): string {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length) return (words[0][0] + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
  return email.slice(0, 1).toUpperCase();
}

/** A sentence for a failed user-area call. */
export function userError(err: unknown): string {
  const code = err instanceof AuthError ? err.code : "server";
  switch (code) {
    case "rate_limited": return "That's a lot of changes in a short time. Please wait a minute and try again.";
    case "resume_limit": return "You've saved the most resumes we keep (20). Delete one to add another.";
    case "invalid_input": return "Something in there didn't look right. Check the fields and try again.";
    case "backend_down": return "We can't reach the service right now. Please try again in a moment.";
    default: return "Something went wrong on our side. Please try again in a moment.";
  }
}
