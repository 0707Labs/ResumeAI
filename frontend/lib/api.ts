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
  if (status >= 400 && status < 500) return "invalid_input";
  return "server";
}

/** 402 from any call: show the out-of-credits dialog (mounted once in AppShell). */
export function announceOutOfCredits() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event("rt:out-of-credits"));
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

/** One id per resume + job analysis, sent as X-Analysis-Id so the backend can total
 * LLM cost per analysis. Random, not tied to the person; kept for the tab's session. */
const ANALYSIS_KEY = "rt_analysis_id";

export function currentAnalysisId(): string | null {
  try {
    return sessionStorage.getItem(ANALYSIS_KEY);
  } catch {
    return null;
  }
}

function startAnalysis(): void {
  try {
    sessionStorage.setItem(ANALYSIS_KEY, crypto.randomUUID());
  } catch {
    /* storage blocked: costs are just not grouped */
  }
}

const json = (body: unknown): RequestInit => {
  const id = currentAnalysisId();
  return {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(id ? { "X-Analysis-Id": id } : {}) },
    body: JSON.stringify(body),
  };
};

/** The double-submit CSRF token: the backend's rt_csrf cookie, fetched if not set yet. */
export async function csrfToken(): Promise<string> {
  const fromCookie = /(?:^|;\s*)(?:__Host-)?rt_csrf=([^;]+)/.exec(typeof document === "undefined" ? "" : document.cookie)?.[1];
  return fromCookie ? decodeURIComponent(fromCookie) : (await request(S.CsrfToken, "/api/auth/csrf")).csrf_token;
}

/** A state-changing auth/account call: same origin, with the CSRF header. */
async function authPost(path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = { "X-CSRF-Token": await csrfToken() };
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

  /** Starts a new analysis: later calls are grouped under a fresh analysis id. */
  analyze: (resume: S.Resume, jd: S.JobDescription, useLLM = true) => {
    startAnalysis();
    return request(S.GapAnalysis, "/api/gap/analyze", json({ resume, jd, use_llm: useLLM }));
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

  /** What the download will contain, after the same server-side checks. */
  exportPreview: (resume: S.Resume, tailored: S.TailoredResume, analysis: S.GapAnalysis | null, jdText: string,
    signal?: AbortSignal) =>
    request(S.ExportPreview, "/api/export/preview", { ...json({ resume, tailored, analysis, jd_text: jdText }), signal }),

  async exportFile(fmt: "docx" | "pdf", resume: S.Resume, tailored: S.TailoredResume, analysis: S.GapAnalysis | null, jdText: string) {
    let res: Response;
    try {
      res = await fetch(`${API_URL}/api/export/${fmt}`, json({ resume, tailored, analysis, jd_text: jdText }));
    } catch {
      throw new ApiError("backend_down", 0);
    }
    if (!res.ok) {
      const detail = await readDetail(res);
      throw new ApiError(classify(res.status, detail), res.status, detail);
    }
    const filename = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? `resume.${fmt}`;
    return { blob: await res.blob(), filename };
  },
};

export function messageFor(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return FRIENDLY.server;
}
