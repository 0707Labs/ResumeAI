"use client";

import { useEffect, useState } from "react";

import { GapStep } from "@/components/GapStep";
import { JobStep } from "@/components/JobStep";
import { MentorStep } from "@/components/MentorStep";
import { ResumeStep } from "@/components/ResumeStep";
import { ScoreStep } from "@/components/ScoreStep";
import { TailorStep } from "@/components/TailorStep";
import { ErrorBanner } from "@/components/ui";
import * as api from "@/lib/api";
import type {
  GapAnalysis,
  JobDescription,
  MentorAdvice,
  Resume,
  ReviewStatus,
  ScoreResponse,
  TailoredResume,
} from "@/lib/types";

type Step = "resume" | "job" | "gaps" | "tailor" | "score" | "mentor";
const STEPS: { id: Step; label: string }[] = [
  { id: "resume", label: "Resume" },
  { id: "job", label: "Job description" },
  { id: "gaps", label: "Gaps & questions" },
  { id: "tailor", label: "Tailor & review" },
  { id: "score", label: "ATS score" },
  { id: "mentor", label: "Mentor" },
];

export default function Home() {
  const [step, setStep] = useState<Step>("resume");
  const [busy, setBusy] = useState<Step | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [llm, setLlm] = useState<{ configured: boolean; enabled: boolean } | null>(null);

  const [resume, setResume] = useState<Resume | null>(null);
  const [jdText, setJdText] = useState("");
  const [jd, setJd] = useState<JobDescription | null>(null);
  const [analysis, setAnalysis] = useState<GapAnalysis | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [tailored, setTailored] = useState<TailoredResume | null>(null);
  const [score, setScore] = useState<ScoreResponse | null>(null);
  const [advice, setAdvice] = useState<MentorAdvice | null>(null);

  useEffect(() => {
    api.health()
      .then((h) => setLlm({ configured: h.llm_configured, enabled: h.llm_configured }))
      .catch(() => setError(`Can't reach the backend at ${api.API_URL}. Start it with: cd backend && .venv/bin/uvicorn app.main:app --reload`));
  }, []);
  const useLLM = !!llm?.enabled;

  async function run<T>(which: Step, fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(which);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  // Changing an input invalidates everything computed from it.
  const clearFrom = (s: "resume" | "job" | "gaps" | "tailor") => {
    if (s === "resume" || s === "job") { setAnalysis(null); setAnswers({}); }
    if (s !== "tailor") setTailored(null);
    setScore(null);
    setAdvice(null);
  };

  const loadResume = async (file: File) => {
    const r = await run("resume", () => api.parseResume(file));
    if (r) { setResume(r); clearFrom("resume"); }
    return r;
  };

  const parseJob = async (text = jdText) => {
    const j = await run("job", () => api.parseJD(text));
    if (j) { setJd(j); clearFrom("job"); }
    return j;
  };

  const loadSample = async () => {
    const s = await run("resume", api.getSample);
    if (!s) return;
    const r = await loadResume(new File([s.resume_text], "sample_resume.txt", { type: "text/plain" }));
    setJdText(s.jd_text);
    const j = await parseJob(s.jd_text);
    if (r && j) setStep("gaps");
  };

  const analyze = async () => {
    if (!resume || !jd) return;
    const a = await run("gaps", () => api.analyzeGaps(resume, jd, useLLM));
    if (a) {
      setAnalysis(a);
      setAnswers(Object.fromEntries(a.items.filter((i) => i.question).map((i) => [i.question!.id, i.question!.answer ?? ""])));
      clearFrom("gaps");
    }
  };

  const saveAnswers = async () => {
    if (!analysis) return;
    const a = await run("gaps", () => api.submitAnswers(analysis, answers));
    if (a) { setAnalysis(a); setAdvice(null); }
  };

  const doTailor = async () => {
    if (!resume || !jd || !analysis) return;
    const t = await run("tailor", () => api.tailorResume(resume, jd, analysis, useLLM));
    if (t) { setTailored(t); setScore(null); }
  };

  const setReview = (id: string, review: ReviewStatus) => {
    setTailored((t) => t && { ...t, bullets: t.bullets.map((b) => (b.id === id ? { ...b, review } : b)) });
  };

  const editBullet = async (id: string, text: string, answerIds: string[]) => {
    if (!resume || !tailored || !jd) return;
    const b = tailored.bullets.find((x) => x.id === id);
    if (!b) return;
    const edited = { ...b, text, source_answer_ids: answerIds, change_type: "reword" as const, review: "pending" as const };
    const res = await run("tailor", () => api.verifyBullets(resume, [edited], analysis, jd.raw_text, null));
    if (res) setTailored((t) => t && { ...t, bullets: t.bullets.map((x) => (x.id === id ? res.bullets[0] : x)) });
  };

  const approveAll = () => {
    setTailored((t) => t && {
      ...t,
      bullets: t.bullets.map((b) => (b.verification?.passed && b.review !== "rejected" ? { ...b, review: "approved" } : b)),
      summary_review: t.summary_verification?.passed && t.summary_review !== "rejected" ? "approved" : t.summary_review,
    });
  };

  const doScore = async () => {
    if (!resume || !jd) return;
    const s = await run("score", () => api.scoreResume(resume, jd, tailored, analysis, useLLM));
    if (s) setScore(s);
  };

  const doMentor = async () => {
    if (!resume || !jd || !analysis) return;
    const result = await run("mentor", async () => {
      const s = score ?? (await api.scoreResume(resume, jd, tailored, analysis, useLLM));
      if (!score) setScore(s);
      return api.getMentor(resume, jd, analysis, s.before, useLLM);
    });
    if (result) setAdvice(result);
  };

  const doExport = async (fmt: "docx" | "pdf") => {
    if (!resume || !tailored) return;
    const out = await run("tailor", () => api.exportResume(fmt, resume, tailored, analysis, jd?.raw_text ?? ""));
    if (!out) return;
    const url = URL.createObjectURL(out.blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = out.filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const confirmed = (analysis?.items ?? [])
    .filter((i) => i.question?.answer && i.question.answer_kind === "confirmed")
    .map((i) => ({ id: i.question!.id, requirement: i.requirement_text, answer: i.question!.answer! }));

  const done: Record<Step, boolean> = {
    resume: !!resume, job: !!jd, gaps: !!analysis, tailor: !!tailored, score: !!score, mentor: !!advice,
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 md:px-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Resume Tailor</h1>
          <p className="text-sm text-slate-500">Tailor to the job. Never invent experience.</p>
        </div>
        {llm && (
          <label className={`flex items-center gap-2 text-sm ${llm.configured ? "text-slate-700" : "text-slate-400"}`}
            title={llm.configured ? "Use Claude for gap review, rewriting, semantic scoring, and mentor wording" : "Set ANTHROPIC_API_KEY on the backend to enable Claude"}>
            <input type="checkbox" checked={llm.enabled} disabled={!llm.configured}
              onChange={(e) => setLlm({ ...llm, enabled: e.target.checked })} />
            Use Claude {llm.configured ? "" : "(no API key, rules only)"}
          </label>
        )}
      </header>

      <div className="grid gap-6 md:grid-cols-[13rem_1fr]">
        <nav aria-label="Steps" className="flex gap-1 overflow-x-auto md:flex-col">
          {STEPS.map((s, i) => (
            <button key={s.id} onClick={() => setStep(s.id)}
              className={`flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${step === s.id ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-200/60"}`}>
              <span className={`flex h-5 w-5 items-center justify-center rounded-full text-xs ${done[s.id] ? "bg-emerald-500 text-white" : step === s.id ? "bg-white/20" : "bg-slate-200 text-slate-600"}`}>
                {done[s.id] ? "✓" : i + 1}
              </span>
              {s.label}
            </button>
          ))}
        </nav>

        <main className="min-w-0">
          <ErrorBanner error={error} onDismiss={() => setError(null)} />
          {step === "resume" && <ResumeStep resume={resume} busy={busy === "resume"} onFile={loadResume} onSample={loadSample} />}
          {step === "job" && <JobStep text={jdText} setText={setJdText} jd={jd} busy={busy === "job"} onParse={() => parseJob()} />}
          {step === "gaps" && (
            <GapStep analysis={analysis} answers={answers} setAnswer={(q, t) => setAnswers({ ...answers, [q]: t })}
              busy={busy === "gaps"} ready={!!resume && !!jd} onAnalyze={analyze} onSaveAnswers={saveAnswers} />
          )}
          {step === "tailor" && (
            <TailorStep resume={resume} tailored={tailored} answers={confirmed} busy={busy === "tailor"} ready={!!analysis}
              onTailor={doTailor} onReview={setReview} onEdit={editBullet}
              onSummaryReview={(r) => setTailored((t) => t && { ...t, summary_review: r })}
              onApproveAll={approveAll} onExport={doExport} />
          )}
          {step === "score" && <ScoreStep score={score} busy={busy === "score"} ready={!!resume && !!jd} onScore={doScore} />}
          {step === "mentor" && <MentorStep advice={advice} busy={busy === "mentor"} ready={!!analysis} onRun={doMentor} />}

          <div className="mt-6 flex justify-between">
            {STEPS.findIndex((s) => s.id === step) > 0 ? (
              <button className="text-sm text-slate-600 hover:text-slate-900" onClick={() => setStep(STEPS[STEPS.findIndex((s) => s.id === step) - 1].id)}>← Back</button>
            ) : <span />}
            {STEPS.findIndex((s) => s.id === step) < STEPS.length - 1 && (
              <button className="text-sm font-medium text-slate-900 hover:underline" onClick={() => setStep(STEPS[STEPS.findIndex((s) => s.id === step) + 1].id)}>Next →</button>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
