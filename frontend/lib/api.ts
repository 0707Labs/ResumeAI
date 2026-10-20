import type {
  ATSReport,
  GapAnalysis,
  JobDescription,
  MentorAdvice,
  Resume,
  ScoreResponse,
  TailoredBullet,
  TailoredResume,
  VerificationResult,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* not JSON */
  }
  return `${res.status} ${res.statusText}`;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, `Can't reach the backend at ${API_URL}. Is it running?`);
  }
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  return res.json() as Promise<T>;
}

export async function health(): Promise<{ status: string; llm_configured: boolean }> {
  const res = await fetch(`${API_URL}/health`);
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  return res.json();
}

export async function getSample(): Promise<{ resume_text: string; jd_text: string }> {
  const res = await fetch(`${API_URL}/api/sample`);
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  return res.json();
}

export async function parseResume(file: File): Promise<Resume> {
  const form = new FormData();
  form.append("file", file);
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/resume/parse`, { method: "POST", body: form });
  } catch {
    throw new ApiError(0, `Can't reach the backend at ${API_URL}. Is it running?`);
  }
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  return res.json();
}

export const parseJD = (text: string) => post<JobDescription>("/api/jd/parse", { text });

export const analyzeGaps = (resume: Resume, jd: JobDescription, use_llm: boolean) =>
  post<GapAnalysis>("/api/gap/analyze", { resume, jd, use_llm });

export const submitAnswers = (analysis: GapAnalysis, answers: Record<string, string>) =>
  post<GapAnalysis>("/api/gap/answers", { analysis, answers });

export const tailorResume = (resume: Resume, jd: JobDescription, analysis: GapAnalysis, use_llm: boolean) =>
  post<TailoredResume>("/api/tailor", { resume, jd, analysis, use_llm });

export const verifyBullets = (
  resume: Resume,
  bullets: TailoredBullet[],
  analysis: GapAnalysis | null,
  jd_text: string,
  summary: string | null,
) =>
  post<{ bullets: TailoredBullet[]; summary_verification: VerificationResult | null }>("/api/verify", {
    resume,
    bullets,
    analysis,
    jd_text,
    summary,
  });

export const scoreResume = (
  resume: Resume,
  jd: JobDescription,
  tailored: TailoredResume | null,
  analysis: GapAnalysis | null,
  use_llm: boolean,
) => post<ScoreResponse>("/api/ats/score", { resume, jd, tailored, analysis, use_llm });

export const getMentor = (
  resume: Resume,
  jd: JobDescription,
  analysis: GapAnalysis,
  ats: ATSReport,
  use_llm: boolean,
) => post<MentorAdvice>("/api/mentor", { resume, jd, analysis, ats, use_llm });

export async function exportResume(
  fmt: "docx" | "pdf",
  resume: Resume,
  tailored: TailoredResume,
  analysis: GapAnalysis | null,
  jd_text: string,
): Promise<{ blob: Blob; filename: string }> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/export/${fmt}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resume, tailored, analysis, jd_text }),
    });
  } catch {
    throw new ApiError(0, `Can't reach the backend at ${API_URL}. Is it running?`);
  }
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  const cd = res.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(cd)?.[1] ?? `resume_tailored.${fmt}`;
  return { blob: await res.blob(), filename };
}
