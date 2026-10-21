"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { useHydrated } from "@/components/AppShell";
import { ArrowRightIcon, ShieldIcon } from "@/components/icons";
import { ResumePreview } from "@/components/ResumePreview";
import { Alert, Button, Card, Label, inputClass } from "@/components/ui";
import { UploadDropzone } from "@/components/UploadDropzone";
import { api, messageFor } from "@/lib/api";
import type { Resume } from "@/lib/schemas";
import { useSession } from "@/lib/store";

const MIN_JD_CHARS = 80;

type Tab = "upload" | "paste";
type Stage = null | "resume" | "jd" | "gaps";
const STAGE_TEXT: Record<Exclude<Stage, null>, string> = {
  resume: "Reading your resume…",
  jd: "Reading the job description…",
  gaps: "Comparing the job with your resume…",
};

export default function InputPage() {
  const hydrated = useHydrated();
  const router = useRouter();
  const s = useSession();

  const [tab, setTab] = useState<Tab>("upload");
  const [pasteDraft, setPasteDraft] = useState("");
  const [resumeBusy, setResumeBusy] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>(null);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  // Restore the paste tab after a refresh.
  useEffect(() => {
    if (!hydrated) return;
    if (s.resumeInput?.mode === "paste") {
      setTab("paste");
      setPasteDraft(s.resumeInput.text);
    }
  }, [hydrated]); // first hydration only

  const pasteIsCurrent = s.resumeInput?.mode === "paste" && s.resumeInput.text === pasteDraft && !!s.resume;
  const resumeReady = tab === "upload" ? s.resumeInput?.mode === "file" && !!s.resume : pasteDraft.trim().length > 0;
  const jdReady = s.jdText.trim().length >= MIN_JD_CHARS;
  const busy = stage !== null || resumeBusy;

  async function loadFile(file: File) {
    setResumeError(null);
    setResumeBusy(true);
    try {
      const resume = await api.parseResumeFile(file);
      s.setResume(resume, { mode: "file", fileName: file.name });
    } catch (e) {
      setResumeError(messageFor(e));
    } finally {
      setResumeBusy(false);
    }
  }

  async function checkPaste(text = pasteDraft): Promise<Resume | null> {
    setResumeError(null);
    setResumeBusy(true);
    try {
      const resume = await api.parseResumeText(text);
      s.setResume(resume, { mode: "paste", text });
      return resume;
    } catch (e) {
      setResumeError(messageFor(e));
      return null;
    } finally {
      setResumeBusy(false);
    }
  }

  function pasteInstead() {
    setPasteDraft(s.resume?.raw_text ?? "");
    setTab("paste");
  }

  async function loadSample() {
    setAnalyzeError(null);
    try {
      const sample = await api.sample();
      setTab("paste");
      setPasteDraft(sample.resume_text);
      s.setJobInputs({ jdText: sample.jd_text, jobTitle: "", company: "" });
      await checkPaste(sample.resume_text);
    } catch (e) {
      setResumeError(messageFor(e));
    }
  }

  async function analyze() {
    setAnalyzeError(null);
    try {
      let resume = s.resume;
      if (tab === "paste" && !pasteIsCurrent) {
        setStage("resume");
        resume = await api.parseResumeText(pasteDraft);
        s.setResume(resume, { mode: "paste", text: pasteDraft });
      }
      if (!resume) return;
      setStage("jd");
      const parsed = await api.parseJD(s.jdText);
      // The user's own title/company win over what we guessed from the text.
      const jd = {
        ...parsed,
        title: s.jobTitle.trim() || parsed.title,
        company: s.company.trim() || parsed.company,
      };
      setStage("gaps");
      const analysis = await api.analyze(resume, jd);
      s.setAnalyzed(jd, analysis);
      router.push("/analysis");
    } catch (e) {
      setAnalyzeError(messageFor(e));
    } finally {
      setStage(null);
    }
  }

  const missing: string[] = [];
  if (!resumeReady) missing.push(tab === "upload" ? "Upload your resume (or paste it as text)." : "Paste your resume text.");
  if (!jdReady) missing.push("Paste the job description (a few lines at least).");

  return (
    <div className="space-y-6">
      <div className="max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">Let&apos;s look at this job together</h1>
        <p className="mt-2 text-muted">
          Share your resume and the job description. We&apos;ll show what already matches, ask about anything that
          seems missing, and suggest honest edits for you to review.
        </p>
      </div>

      <div className="flex items-start gap-3 rounded-xl border border-accent/30 bg-accent-soft px-4 py-3 text-sm">
        <ShieldIcon className="mt-0.5 h-5 w-5 text-accent" />
        <p>
          <span className="font-medium">We never add experience you don&apos;t have. You approve every change.</span>{" "}
          <span className="text-muted">Your resume stays in this tab and is only sent to our analysis service.</span>
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card aria-labelledby="resume-heading">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="resume-heading" className="text-lg font-semibold">Your resume</h2>
            <button type="button" onClick={loadSample} disabled={busy}
              className="text-sm text-accent underline-offset-2 hover:underline disabled:opacity-50">
              No resume handy? Try a sample
            </button>
          </div>

          <Tabs tab={tab} onChange={setTab} />

          <div className="mt-4">
            {tab === "upload" ? (
              <div role="tabpanel" id="panel-upload" aria-labelledby="tab-upload">
                <UploadDropzone
                  onFile={loadFile}
                  onReject={setResumeError}
                  busy={resumeBusy}
                  fileName={s.resumeInput?.mode === "file" ? s.resumeInput.fileName : null}
                />
                {resumeError && <div className="mt-4"><Alert tone="bad" role="alert" title="We couldn't use that file">{resumeError}</Alert></div>}
                {s.resume && s.resumeInput?.mode === "file" && <ResumePreview resume={s.resume} onPasteInstead={pasteInstead} />}
              </div>
            ) : (
              <div role="tabpanel" id="panel-paste" aria-labelledby="tab-paste">
                <Label htmlFor="resume-text" hint="(plain text is fine)">Resume text</Label>
                <textarea
                  id="resume-text"
                  value={pasteDraft}
                  onChange={(e) => setPasteDraft(e.target.value)}
                  rows={12}
                  placeholder={"Jane Doe\njane@example.com\n\nExperience\nData Analyst | Acme | 2022 – Present\n• Built…"}
                  className={`${inputClass} font-mono`}
                />
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <Button variant="secondary" onClick={() => checkPaste()} busy={resumeBusy} disabled={!pasteDraft.trim()}>
                    Check what we read
                  </Button>
                  {pasteIsCurrent && <span className="text-sm text-ok">Up to date</span>}
                </div>
                {resumeError && <div className="mt-4"><Alert tone="bad" role="alert" title="We couldn't read that">{resumeError}</Alert></div>}
                {s.resume && pasteIsCurrent && (
                  <ResumePreview resume={s.resume} onPasteInstead={() => document.getElementById("resume-text")?.focus()} />
                )}
              </div>
            )}
          </div>
        </Card>

        <JobCard />
      </div>

      <Card as="div" className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 space-y-2">
          <div aria-live="polite" className="text-sm">
            {stage ? <span className="text-fg">{STAGE_TEXT[stage]}</span>
              : missing.length > 0 ? <span className="text-muted">Before we can analyze:</span>
              : <span className="text-ok">Ready when you are.</span>}
          </div>
          {!stage && missing.length > 0 && (
            <ul id="analyze-missing" className="list-inside list-disc text-sm text-muted">
              {missing.map((m) => <li key={m}>{m}</li>)}
            </ul>
          )}
          {analyzeError && <Alert tone="bad" role="alert" title="Analysis didn't finish">{analyzeError}</Alert>}
        </div>
        <Button
          onClick={analyze}
          busy={stage !== null}
          disabled={!hydrated || !resumeReady || !jdReady || resumeBusy}
          aria-describedby={missing.length ? "analyze-missing" : undefined}
          className="shrink-0 px-6"
        >
          Analyze <ArrowRightIcon />
        </Button>
      </Card>
    </div>
  );
}

function Tabs({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  const refs = useRef<Record<Tab, HTMLButtonElement | null>>({ upload: null, paste: null });
  const tabs: { id: Tab; label: string }[] = [
    { id: "upload", label: "Upload a file" },
    { id: "paste", label: "Paste text" },
  ];
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const next: Tab = tab === "upload" ? "paste" : "upload";
    onChange(next);
    refs.current[next]?.focus();
  };
  return (
    <div role="tablist" aria-label="How to add your resume" className="mt-4 inline-flex rounded-lg bg-surface-2 p-1" onKeyDown={onKey}>
      {tabs.map((t) => (
        <button
          key={t.id}
          ref={(el) => { refs.current[t.id] = el; }}
          id={`tab-${t.id}`}
          role="tab"
          type="button"
          aria-selected={tab === t.id}
          aria-controls={`panel-${t.id}`}
          tabIndex={tab === t.id ? 0 : -1}
          onClick={() => onChange(t.id)}
          className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === t.id ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg"}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function JobCard() {
  const s = useSession();
  const countId = useId();
  const len = s.jdText.trim().length;
  return (
    <Card aria-labelledby="job-heading">
      <h2 id="job-heading" className="text-lg font-semibold">The job</h2>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <Label htmlFor="job-title" hint="(optional)">Job title</Label>
          <input id="job-title" value={s.jobTitle} onChange={(e) => s.setJobInputs({ jobTitle: e.target.value })}
            placeholder="e.g. Senior Data Analyst" className={inputClass} autoComplete="off" />
        </div>
        <div>
          <Label htmlFor="company" hint="(optional)">Company</Label>
          <input id="company" value={s.company} onChange={(e) => s.setJobInputs({ company: e.target.value })}
            placeholder="e.g. Northwind" className={inputClass} autoComplete="off" />
        </div>
      </div>
      <div className="mt-4">
        <Label htmlFor="jd-text">Job description</Label>
        <textarea
          id="jd-text"
          value={s.jdText}
          onChange={(e) => s.setJobInputs({ jdText: e.target.value })}
          rows={14}
          aria-describedby={countId}
          placeholder="Paste the full posting, including the requirements and nice-to-haves."
          className={inputClass}
        />
        <p id={countId} className="mt-1 text-xs text-muted">
          {len === 0 ? "Include the requirements section; that's what we compare against."
            : len < MIN_JD_CHARS ? `A little more, please: that looks shorter than a full posting.`
            : `${len.toLocaleString()} characters`}
        </p>
      </div>
    </Card>
  );
}
