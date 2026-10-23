/**
 * Typed wrappers for the FastAPI backend. Every response is validated with zod,
 * so a backend/UI mismatch shows up as a clear error instead of a broken screen.
 *
 * Privacy: these are the only network calls the app makes, and they go only to
 * our own origin, which Next.js proxies to the backend (or NEXT_PUBLIC_API_URL if set).
 * No analytics, no third parties.
 */
import type { z } from "zod";

import * as S from "./schemas";

/** Same origin in the browser (see next.config.ts rewrites); the backend itself under Node (contract tests). */
export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? (typeof window === "undefined" ? "http://localhost:8000" : "")
).replace(/\/$/, "");

export type ApiErrorKind =
  | "backend_down"
  | "unsupported_file"
  | "file_too_large"
  | "no_text"
  | "unreadable_file"
  | "invalid_input"
  | "bad_response"
  | "out_of_credits"
  | "tailoring_limit"
  | "sign_in_required"
  | "analysis_expired"
  | "rate_limited"
  | "forbidden"
  | "reauth_required"
  | "analyses_paused"
  | "server";

const FRIENDLY: Record<ApiErrorKind, string> = {
  backend_down:
    "We can't reach the analysis service right now. If you're running it locally, start the backend and try again.",
  unsupported_file: "That file type isn't supported. Please upload a PDF or DOCX, or paste your resume as text.",
  file_too_large: "That file is over 5 MB. Try exporting a smaller PDF, or paste the text instead.",
  no_text:
    "We couldn't find any text in that file. It may be a scanned image. Try a text-based PDF or DOCX, or paste your resume as text.",
  unreadable_file: "We couldn't open that file. It might be damaged. Try saving it again, or paste the text instead.",
  invalid_input: "Something in the input didn't look right.",
  bad_response: "The service sent back something we didn't expect. Please try again.",
  out_of_credits:
    "Downloading the clean file needs a credit or a pass. Tailoring and review stay free.",
  tailoring_limit:
    "You've used this month's free tailorings. Get credits or a pass to keep going, or wait for them to reset at the start of next month.",
  sign_in_required: "Sign in to download your tailored resume. Your work here stays in this tab.",
  analysis_expired:
    "The free re-download period for this resume has passed, and we've deleted our copy of it. Tailor it again to download a new file.",
  rate_limited: "That's a lot of requests in a short time. Please wait a minute and try again.",
  forbidden: "Your account can't do that.",
  reauth_required: "This change needs a fresh sign-in. Sign in again to confirm it's you.",
  analyses_paused:
    "New analyses are paused for a short while on our side. Your resume and job description are still here; try again later.",
  server: "Something went wrong on our side. Please try again in a moment.",
};

export class ApiError extends Error {
  constructor(
    public kind: ApiErrorKind,
    public status: number,
    public detail?: string,
  ) {
    super(FRIENDLY[kind]);
    this.name = "ApiError";
  }
}

async function readDetail(res: Response): Promise<string | undefined> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) return body.detail.map((d: { msg?: string }) => d.msg).join("; ");
  } catch {
    /* not JSON */
  }
  return undefined;
}

/** Map an HTTP failure to a kind the UI can explain. Exported for tests. */
export function classify(status: number, detail?: string): ApiErrorKind {
  if (status === 415) return "unsupported_file";
  if (status === 413) return "file_too_large";
  if (status === 422 && detail && /no text found|scanned/i.test(detail)) return "no_text";
  if (status === 422 && detail && /could not read/i.test(detail)) return "unreadable_file";
  if (status === 429) return "rate_limited";
  if (status === 401 && detail === "reauth_required") return "reauth_required";
  if (status === 403 && detail === "forbidden") return "forbidden";
  if (status === 503 && detail === "analyses_paused") return "analyses_paused";
  if (status >= 400 && status < 500) return "invalid_input";
  return "server";
}

/** Why the pricing dialog opened: past the free tailorings, or a download that needs paying for. */
export type OutOfCredits = { reason: "tailoring" } | { reason: "download"; fmt: "docx" | "pdf" };

/** 402 from any call: show the pricing dialog (mounted once in AppShell). */
export function announceOutOfCredits(detail: OutOfCredits = { reason: "tailoring" }) {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("rt:out-of-credits", { detail }));
}

async function request<T extends z.ZodType>(schema: T, path: string, init?: RequestInit): Promise<z.infer<T>> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch (e) {
    // A cancelled request (newer one superseded it) isn't a backend problem.
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError("backend_down", 0);
  }
  if (!res.ok) {
    if (res.status === 402) announceOutOfCredits();
    const detail = await readDetail(res);
    throw new ApiError(classify(res.status, detail), res.status, detail);
  }
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    throw new ApiError("bad_response", res.status);
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    throw new ApiError("bad_response", res.status, parsed.error.issues.slice(0, 3).map((i) => `${i.path.join(".")}: ${i.message}`).join("; "));
  }
  return parsed.data;
}

/** The server-side analysis for this resume + job, sent as X-Analysis-Id. The backend uses
 * Claude only for the caller's own analysis (signed out: rules-only), and the download is
 * charged to it once. Kept for the tab's session. */
const ANALYSIS_KEY = "rt_analysis_id";

export function currentAnalysisId(): string | null {
  try {
    return sessionStorage.getItem(ANALYSIS_KEY);
  } catch {
    return null;
  }
}

function setAnalysisId(id: string | null): void {
  try {
    if (id) sessionStorage.setItem(ANALYSIS_KEY, id);
    else sessionStorage.removeItem(ANALYSIS_KEY);
  } catch {
    /* storage blocked: later calls run rules-only */
  }
}

/** What we tell someone whose analysis started over the daily Claude cap. Exported for tests. */
export function dailyLimitNote(perDay?: number): string {
  const used = perDay === undefined ? "today's Claude analyses" : `today's ${perDay} Claude ${perDay === 1 ? "analysis" : "analyses"}`;
  return `You've used ${used}, so this one uses our rules-based checks only (no AI rewriting). ` +
    "Claude is available again from 00:00 UTC. Reviewing and downloading work as usual.";
}

/** Start a tailoring: the server pins this resume and job description to it. Spends
 * nothing (the download is what's paid). Signed out (401): no analysis, rules-only.
 * 402: past this month's free tailorings with no pass or credits, so the pricing dialog
 * opens and this throws. Returns a note to show when this analysis can't use Claude
 * (over the daily cap), else null. */
async function startAnalysis(resume: S.Resume, jd: S.JobDescription): Promise<string | null> {
  setAnalysisId(null);
  const res = await authPost("/api/analyses", { resume, jd }, { "Idempotency-Key": crypto.randomUUID() });
  if (res.status === 401) return null;
  if (!res.ok) {
    if (res.status === 402) announceOutOfCredits({ reason: "tailoring" });
    const detail = await readDetail(res);
    throw new ApiError(res.status === 402 ? "tailoring_limit" : classify(res.status, detail), res.status, detail);
  }
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    throw new ApiError("bad_response", res.status);
  }
  const parsed = S.AnalysisStarted.safeParse(body);
  if (!parsed.success) throw new ApiError("bad_response", res.status);
  setAnalysisId(parsed.data.analysis_id);
  return parsed.data.claude ? null : dailyLimitNote(parsed.data.claude_per_day);
}

const json = (body: unknown): RequestInit => {
  const id = currentAnalysisId();
  return {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(id ? { "X-Analysis-Id": id } : {}) },
    body: JSON.stringify(body),
  };
};

/** False when there's certainly no session: sign-in always sets rt_csrf and sign-out clears it.
 * Lets public pages skip /api/me (and its 401) for visitors who never signed in. */
export function mightBeSignedIn(): boolean {
  return typeof document !== "undefined" && /(?:^|;\s*)(?:__Host-)?rt_csrf=/.test(document.cookie);
}

/** The double-submit CSRF token: the backend's rt_csrf cookie, fetched if not set yet. */
export async function csrfToken(): Promise<string> {
  const fromCookie = /(?:^|;\s*)(?:__Host-)?rt_csrf=([^;]+)/.exec(typeof document === "undefined" ? "" : document.cookie)?.[1];
  return fromCookie ? decodeURIComponent(fromCookie) : (await request(S.CsrfToken, "/api/auth/csrf")).csrf_token;
}

/** A state-changing auth/account call: same origin, with the CSRF header. */
async function authPost(path: string, body?: unknown, extra: Record<string, string> = {}): Promise<Response> {
  const headers: Record<string, string> = { ...extra, "X-CSRF-Token": await csrfToken() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  try {
    return await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError("backend_down", 0);
  }
}

export const ACCEPTED_TYPES = [".pdf", ".docx"] as const;

export const api = {
  health: () => request(S.Health, "/health"),

  /** The signed-in user, or null when there's no session. */
  async me(): Promise<S.Me | null> {
    try {
      return await request(S.Me, "/api/me", { credentials: "same-origin" });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return null;
      throw e;
    }
  },

  /** Free tailorings left this month and what the next one uses; null when signed out. */
  async allowance(): Promise<S.Allowance | null> {
    try {
      return await request(S.Allowance, "/api/analyses/allowance", { credentials: "same-origin" });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return null;
      throw e;
    }
  },

  async logout(): Promise<void> {
    const res = await authPost("/api/auth/logout");
    if (!res.ok) throw new ApiError(classify(res.status, await readDetail(res)), res.status);
  },
  sample: () => request(S.Sample, "/api/sample"),

  parseResumeFile(file: File) {
    const form = new FormData();
    form.append("file", file);
    return request(S.Resume, "/api/resume/parse", { method: "POST", body: form });
  },

  /** Pasted text goes through the same parser as a .txt upload. */
  parseResumeText(text: string) {
    return api.parseResumeFile(new File([text], "pasted-resume.txt", { type: "text/plain" }));
  },

  parseJD: (text: string) => request(S.JobDescription, "/api/jd/parse", json({ text })),

  /** Starts a new analysis (when signed in; see startAnalysis), then runs the gap step.
   * Over the daily Claude cap the gap step's "Rules only" note becomes dailyLimitNote. */
  analyze: async (resume: S.Resume, jd: S.JobDescription, useLLM = true) => {
    const limited = await startAnalysis(resume, jd);
    const gap = await request(S.GapAnalysis, "/api/gap/analyze", json({ resume, jd, use_llm: useLLM }));
    return limited && useLLM ? { ...gap, notes: [limited, ...gap.notes.filter((n) => !n.startsWith("Rules only"))] } : gap;
  },

  /** Explicit yes/no/skip per question id. "skip" clears an earlier answer. */
  submitAnswers: (analysis: S.GapAnalysis, answers: Record<string, { choice: "yes" | "no" | "skip"; text: string }>) =>
    request(S.GapAnalysis, "/api/gap/answers", json({ analysis, answers })),

  tailor: (resume: S.Resume, jd: S.JobDescription, analysis: S.GapAnalysis, useLLM = true) =>
    request(S.TailoredResume, "/api/tailor", json({ resume, jd, analysis, use_llm: useLLM })),

  verify: (resume: S.Resume, bullets: S.TailoredBullet[], analysis: S.GapAnalysis | null, jdText: string, summary: string | null) =>
    request(S.VerifyResponse, "/api/verify", json({ resume, bullets, analysis, jd_text: jdText, summary })),

  /** approvedOnly: "after" counts only approved bullets (what export will use). */
  score: (resume: S.Resume, jd: S.JobDescription, tailored: S.TailoredResume | null, analysis: S.GapAnalysis | null,
    { useLLM = false, approvedOnly = false, signal }: { useLLM?: boolean; approvedOnly?: boolean; signal?: AbortSignal } = {}) =>
    request(S.ScoreResponse, "/api/ats/score", {
      ...json({ resume, jd, tailored, analysis, use_llm: useLLM, approved_only: approvedOnly }),
      signal,
    }),

  /** ats: the "before" report; omit and the backend computes it. */
  mentor: (resume: S.Resume, jd: S.JobDescription, analysis: S.GapAnalysis, ats: S.ATSReport | null = null, useLLM = true) =>
    request(S.MentorAdvice, "/api/mentor", json({ resume, jd, analysis, ats, use_llm: useLLM })),

  /** What the download will contain, after the same server-side checks, as watermarked,
   * partly masked page images (the clean file is only sent after paying). */
  exportPreview: (resume: S.Resume, tailored: S.TailoredResume, analysis: S.GapAnalysis | null, jdText: string,
    { markChanges = true, signal }: { markChanges?: boolean; signal?: AbortSignal } = {}) =>
    request(S.ExportPreview, "/api/export/preview", {
      ...json({ resume, tailored, analysis, jd_text: jdText, mark_changes: markChanges }), signal,
    }),

  /** Pay for a clean download and get its short-lived signed link (the file is built on
   * the server only after the entitlement check). Re-downloading the same tailored resume
   * within the window is free. Needs sign-in: someone who signed in after analyzing gets an
   * analysis started here. 402 opens the pricing dialog for this download. 410
   * analysis_expired: its text was deleted under the retention policy; tailor again. */
  async requestDownload(fmt: "docx" | "pdf", resume: S.Resume, jd: S.JobDescription, tailored: S.TailoredResume,
    analysis: S.GapAnalysis | null): Promise<S.DownloadLink> {
    if (!currentAnalysisId()) await startAnalysis(resume, jd);
    if (!currentAnalysisId()) throw new ApiError("sign_in_required", 401);
    const res = await authPost(`/api/downloads/${fmt}`, { resume, tailored, analysis, jd_text: jd.raw_text },
      { "X-Analysis-Id": currentAnalysisId()! });
    if (!res.ok) {
      if (res.status === 402) announceOutOfCredits({ reason: "download", fmt });
      const detail = await readDetail(res);
      // 410 analysis_expired: the retention purge cleared this analysis, so forget it; the
      // next Analyze or download starts a new one.
      if (res.status === 410 && detail === "analysis_expired") {
        setAnalysisId(null);
        throw new ApiError("analysis_expired", res.status, detail);
      }
      const kind = res.status === 402 ? "out_of_credits" : res.status === 401 ? "sign_in_required" : classify(res.status, detail);
      throw new ApiError(kind, res.status, detail);
    }
    const parsed = S.DownloadLink.safeParse(await res.json().catch(() => undefined));
    if (!parsed.success) throw new ApiError("bad_response", res.status);
    return parsed.data;
  },
};

export function messageFor(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return FRIENDLY.server;
}
