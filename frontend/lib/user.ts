/**
 * The signed-in user area (backend app/api/profile.py). Same rules as auth.ts: our origin
 * only, CSRF on writes, every response validated with its zod schema.
 */
import type { z } from "zod";

import { API_URL, ApiError, csrfToken, messageFor } from "./api";
import { AuthError, call } from "./auth";
import * as S from "./schemas";

async function upload<T extends z.ZodType>(schema: T, path: string, file: File): Promise<z.infer<T>> {
  const form = new FormData();
  form.append("file", file);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "PUT", body: form, credentials: "same-origin", headers: { "X-CSRF-Token": await csrfToken() },
    });
  } catch {
    throw new AuthError("backend_down", 0);
  }
  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail).catch(() => undefined);
    throw new AuthError(typeof detail === "string" ? detail : "server", res.status);
  }
  return schema.parse(await res.json());
}

/** POST /api/account/export and hand the browser the JSON file. */
async function downloadExport(): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/account/export`, {
      method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": await csrfToken() },
    });
  } catch {
    throw new AuthError("backend_down", 0);
  }
  if (!res.ok) throw new AuthError(res.status === 429 ? "rate_limited" : "server", res.status);
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "resume-tailor-export.json";
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

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

  profile: () => call(S.Profile, "/api/profile"),
  updateProfile: (body: { name?: string; phone?: string | null }) =>
    call(S.Profile, "/api/profile", { method: "PATCH", body }),
  uploadAvatar: (file: File) => upload(S.Profile, "/api/profile/avatar", file),
  removeAvatar: () => call(S.Profile, "/api/profile/avatar", { method: "DELETE" }),

  resume: (id: string, version?: number) =>
    call(S.ResumeDetail, `/api/resumes/${id}${version ? `?version=${version}` : ""}`),
  versions: (id: string) => call(S.VersionSummary.array(), `/api/resumes/${id}/versions`),
  addVersion: (id: string, body: { resume: S.Resume; source: "edit" | "upload" | "paste"; file_name?: string }) =>
    call(S.ResumeDetail, `/api/resumes/${id}/versions`, { method: "POST", body }),
  updateResume: (id: string, body: { title?: string; is_default?: true }) =>
    call(S.ResumeSummary, `/api/resumes/${id}`, { method: "PATCH", body }),
  duplicateResume: (id: string) => call(S.ResumeSummary, `/api/resumes/${id}/duplicate`, { method: "POST" }),
  deleteResume: (id: string) => call(null, `/api/resumes/${id}`, { method: "DELETE" }),

  tailorings: (before?: string | null) =>
    call(S.TailoringPage, `/api/tailorings${before ? `?before=${encodeURIComponent(before)}` : ""}`),
  tailoring: (id: string) => call(S.TailoringDetail, `/api/tailorings/${id}`),
  deleteTailoring: (id: string) => call(null, `/api/tailorings/${id}`, { method: "DELETE" }),

  consents: () => call(S.Consents, "/api/account/consents"),
  setResearch: (granted: boolean) => call(S.Consents, "/api/account/consents/research", { method: "PUT", body: { granted } }),
  exportData: downloadExport,

  invites: () => call(S.Invites, "/api/invites"),
  sendInvite: (email: string) => call(S.InviteSent, "/api/invites", { method: "POST", body: { email } }),
  revokeInvite: (id: string) => call(null, `/api/invites/${id}`, { method: "DELETE" }),

  downloads: (before?: string | null) =>
    call(S.DownloadPage, `/api/downloads${before ? `?before=${encodeURIComponent(before)}` : ""}`),
  redownload: (id: string) => call(S.DownloadLink, `/api/downloads/${id}/link`, { method: "POST" }),
  deleteDownload: (id: string) => call(null, `/api/downloads/${id}`, { method: "DELETE" }),

  tickets: () => call(S.Ticket.array(), "/api/support/tickets"),
  sendTicket: (body: { category: S.Ticket["category"]; subject: string; body: string }) =>
    call(S.Ticket, "/api/support/tickets", { method: "POST", body }),
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
  if (err instanceof ApiError) return messageFor(err);  // parsing a file, tailoring: their own wording
  const code = err instanceof AuthError ? err.code : "server";
  switch (code) {
    case "rate_limited": return "That's a lot of changes in a short time. Please wait a minute and try again.";
    case "resume_limit": return "You've saved the most resumes we keep (20). Delete one to add another.";
    case "version_limit": return "This resume has 100 versions, the most we keep. Duplicate it to keep editing.";
    case "bullet_id_mismatch": return "A bullet ended up under the wrong job. Reload the resume and try the edit again.";
    case "avatar_unsupported_type": return "That picture type isn't supported. Use a PNG, JPEG, WebP or GIF.";
    case "avatar_too_large": return "That picture is over 2 MB, or too large in pixels. Try a smaller one.";
    case "no_research_notice": return "The research notice isn't published yet, so this can't be switched on.";
    case "not_found": return "That isn't there any more. It may have been deleted.";
    case "invite_limit": return "You've used all your invites. Revoke one nobody has used to free a slot.";
    case "already_member": return "That address already has an account, so they can sign in now.";
    case "already_invited": return "You've already invited that address; the invite is still open.";
    case "own_email": return "That's your own address. Invite a friend instead.";
    case "disposable_email": return "That looks like a throwaway address. Use your friend's real email.";
    case "already_used": return "Your friend already used that invite, so it can't be revoked.";
    case "email_unavailable": return "We couldn't send email just now. Nothing was used up; try again in a minute.";
    case "file_expired": return "We no longer keep that file. Tailor again to download a new one.";
    case "invalid_input": return "Something in there didn't look right. Check the fields and try again.";
    case "backend_down": return "We can't reach the service right now. Please try again in a moment.";
    default: return "Something went wrong on our side. Please try again in a moment.";
  }
}
