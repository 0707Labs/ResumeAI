"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";

import { EMPTY_PREFERENCES, PreferencesForm } from "@/components/app/PreferencesForm";
import { ErrorState } from "@/components/app/states";
import { CheckIcon } from "@/components/icons";
import { UploadDropzone } from "@/components/UploadDropzone";
import { Button, Card, Label, inputClass } from "@/components/ui";
import { api, messageFor } from "@/lib/api";
import type { Me, PreferencesIn } from "@/lib/schemas";
import { initials, userApi, userError } from "@/lib/user";

/** The resume couldn't be read: its message (from api.ts) says why, in plain words. */
class ParseError extends Error {}

const STEPS = ["About you", "What you're looking for", "Your resume"] as const;

/** First sign-in only: three skippable steps, then the dashboard. */
export default function WelcomePage() {
  const router = useRouter();
  const nameId = useId();
  const [me, setMe] = useState<Me | null>(null);
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [prefs, setPrefs] = useState<PreferencesIn>(EMPTY_PREFERENCES);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);  // the saved resume's file name

  useEffect(() => {
    api.me().then((m) => { setMe(m); setName(m?.name ?? ""); }).catch(() => {});
    userApi.preferences().then(({ updated_at: _, ...p }) => setPrefs(p)).catch(() => {});
  }, []);

  async function run(fn: () => Promise<unknown>, next: () => void) {
    setBusy(true);
    setError(null);
    try { await fn(); next(); } catch (e) { setError(e instanceof ParseError ? e.message : userError(e)); } finally { setBusy(false); }
  }

  const finish = () => run(() => userApi.finishOnboarding(), () => router.replace("/app/dashboard"));
  const advance = () => setStep((s) => s + 1);

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-fg">Welcome to Resume Tailor</h1>
          <p className="mt-1 text-sm text-muted">A few details help us suggest better. Every step is optional.</p>
        </div>
        <Button variant="ghost" onClick={finish} disabled={busy}>Skip setup</Button>
      </div>

      <ol className="mb-6 grid grid-cols-3 gap-2" aria-label="Setup steps">
        {STEPS.map((label, i) => (
          <li key={label} aria-current={i === step ? "step" : undefined}
            className={`rounded-lg border px-3 py-2 text-xs sm:text-sm ${
              i === step ? "border-accent bg-accent-soft font-medium text-fg"
                : i < step ? "border-border text-fg" : "border-border text-muted"}`}>
            <span className="flex items-center gap-1.5">
              {i < step ? <CheckIcon label="Done" /> : <span aria-hidden="true">{i + 1}.</span>}
              {label}
            </span>
          </li>
        ))}
      </ol>

      {error && <div className="mb-4"><ErrorState message={error} /></div>}

      <Card className="space-y-6">
        {step === 0 && (
          <>
            <div className="flex items-center gap-4">
              <div aria-hidden="true" className="flex h-16 w-16 items-center justify-center rounded-full bg-accent-soft text-xl font-semibold text-fg">
                {me ? initials(name || null, me.email) : ""}
              </div>
              <p className="text-sm text-muted">Your initials are your picture for now. {me && <>You signed in as <span className="text-fg">{me.email}</span>.</>}</p>
            </div>
            <div>
              <Label htmlFor={nameId}>Your name</Label>
              <input id={nameId} className={inputClass} value={name} maxLength={80} autoComplete="name"
                onChange={(e) => setName(e.target.value)} />
            </div>
            <StepButtons busy={busy} onSkip={advance}
              onNext={() => run(() => (name.trim() && name.trim() !== me?.name ? userApi.setName(name) : Promise.resolve()), advance)} />
          </>
        )}

        {step === 1 && (
          <>
            <PreferencesForm value={prefs} onChange={setPrefs} />
            <StepButtons busy={busy} onSkip={advance} onBack={() => setStep(0)}
              onNext={() => run(() => userApi.savePreferences(prefs), advance)} />
          </>
        )}

        {step === 2 && (
          <>
            <div>
              <h2 className="font-medium text-fg">Upload your base resume</h2>
              <p className="mt-1 text-sm text-muted">
                We keep it so you don't have to upload it for every job. You can replace or delete it any time.
              </p>
            </div>
            {saved ? (
              <p role="status" className="flex items-center gap-2 rounded-lg bg-ok-bg px-3 py-2 text-sm text-ok">
                <CheckIcon />Saved {saved}.
              </p>
            ) : (
              <UploadDropzone busy={busy} onReject={setError} onFile={(file) => run(async () => {
                let resume;
                try { resume = await api.parseResumeFile(file); } catch (e) { throw new ParseError(messageFor(e)); }
                await userApi.saveResume({ resume, source: "upload", file_name: file.name });
                setSaved(file.name);
              }, () => {})} />
            )}
            <div className="flex flex-wrap justify-between gap-2">
              <Button variant="ghost" onClick={() => setStep(1)} disabled={busy}>Back</Button>
              <Button onClick={finish} busy={busy}>{saved ? "Go to my dashboard" : "Do this later"}</Button>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}


function StepButtons({ busy, onNext, onSkip, onBack }: {
  busy: boolean; onNext: () => void; onSkip: () => void; onBack?: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      {onBack ? <Button variant="ghost" onClick={onBack} disabled={busy}>Back</Button> : <span />}
      <div className="flex gap-2">
        <Button variant="secondary" onClick={onSkip} disabled={busy}>Skip</Button>
        <Button onClick={onNext} busy={busy}>Continue</Button>
      </div>
    </div>
  );
}
