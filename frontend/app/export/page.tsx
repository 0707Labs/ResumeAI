"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useHydrated } from "@/components/AppShell";
import { ExportPanel, type Format } from "@/components/ExportPanel";
import { ResumeDocument } from "@/components/ResumeDocument";
import { Alert, Card, Spinner } from "@/components/ui";
import { ApiError, api, messageFor } from "@/lib/api";
import { saveBlob } from "@/lib/download";
import { counts, exportCheck, withDecisions } from "@/lib/review";
import type { ExportPreview } from "@/lib/schemas";
import { useSession } from "@/lib/store";

export default function ExportPage() {
  const hydrated = useHydrated();
  const { resume, jd, analysis, tailored, decisions } = useSession();
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [markChanges, setMarkChanges] = useState(true);
  const [busy, setBusy] = useState<Format | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [downloaded, setDownloaded] = useState<string | null>(null);

  const payload = useMemo(() => (tailored ? withDecisions(tailored, decisions) : null), [tailored, decisions]);

  useEffect(() => {
    if (!resume || !payload) return;
    const controller = new AbortController();
    setPreviewError(null);
    api.exportPreview(resume, payload, analysis, jd?.raw_text ?? "", controller.signal)
      .then(setPreview)
      .catch((e) => { if (!(e instanceof DOMException && e.name === "AbortError")) setPreviewError(messageFor(e)); });
    return () => controller.abort();
  }, [resume, payload, analysis, jd]);

  if (!hydrated) return null;
  if (!resume || !jd || !tailored || !payload) {
    return (
      <Alert tone="info" title="Nothing to export yet">
        Review your tailored bullets on the <Link href="/review" className="font-medium text-accent underline">review page</Link> first.
      </Alert>
    );
  }

  const check = exportCheck(tailored, decisions);
  const unresolved = tailored.bullets.filter((b) => check.unresolved.includes(b.id));
  const approved = counts(tailored, decisions).approved;

  async function download(fmt: Format) {
    if (!check.ok || !resume || !jd || !payload) return;
    setBusy(fmt);
    setError(null);
    setNeedsSignIn(false);
    setDownloaded(null);
    try {
      const { blob, filename } = await api.exportFile(fmt, resume, jd, payload, analysis);
      saveBlob(blob, filename);
      setDownloaded(filename);
    } catch (e) {
      const signIn = e instanceof ApiError && e.kind === "sign_in_required";
      setNeedsSignIn(signIn);
      setError(signIn ? null : messageFor(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">Preview and download</h1>
        <p className="mt-2 text-muted">
          This is exactly what the file will contain: your approved changes, and everything else as you wrote it.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem] lg:items-start">
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">Preview</h2>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={markChanges} onChange={(e) => setMarkChanges(e.target.checked)} />
              Mark changed lines <span className="text-muted">(not in the file)</span>
            </label>
          </div>
          {previewError && <Alert tone="bad" role="alert" title="Couldn't load the preview">{previewError}</Alert>}
          {preview ? (
            <div className="overflow-x-auto rounded-xl bg-surface-2 p-3 sm:p-6">
              <ResumeDocument resume={preview.resume} changed={new Set(preview.changed_lines)} markChanges={markChanges} />
            </div>
          ) : !previewError && (
            <Card><p role="status" className="flex items-center gap-3 text-muted"><Spinner /> Building the preview…</p></Card>
          )}
        </div>

        <div className="space-y-4 lg:sticky lg:top-4">
          {needsSignIn && (
            <Alert tone="info" title="Sign in to download">
              Tailoring and the preview are free; downloading needs an account.{" "}
              <Link href="/login?next=/export" className="font-medium text-accent underline">Sign in</Link> and
              come back here: your work stays in this tab.
            </Alert>
          )}
          <ExportPanel
            unresolved={unresolved}
            summaryUnresolved={check.summaryUnresolved}
            approvedCount={approved}
            busy={busy}
            error={error}
            downloaded={downloaded}
            onDownload={download}
          />
        </div>
      </div>
    </div>
  );
}
