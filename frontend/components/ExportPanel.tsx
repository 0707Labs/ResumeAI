"use client";

import Link from "next/link";

import type { TailoredBullet } from "@/lib/schemas";

import { CheckIcon, ErrorIcon, FileIcon } from "./icons";
import { Alert, Button } from "./ui";

export type Format = "docx" | "pdf";

/** Download controls. Disabled, with the reasons listed, until every flagged
 * change has a decision. */
export function ExportPanel({ unresolved, summaryUnresolved, approvedCount, busy, error, downloaded, onDownload }: {
  unresolved: TailoredBullet[];
  summaryUnresolved: boolean;
  approvedCount: number;
  busy: Format | null;
  error: string | null;
  downloaded: string | null;
  onDownload: (fmt: Format) => void;
}) {
  const blocked = unresolved.length > 0 || summaryUnresolved;
  return (
    <section aria-labelledby="export-heading" className="rounded-2xl border border-border bg-surface p-5 sm:p-6" data-testid="export-panel">
      <h2 id="export-heading" className="text-lg font-semibold">Download</h2>

      {blocked ? (
        <div id="export-blocked" className="mt-3 space-y-2">
          <p className="flex items-center gap-2 text-sm font-medium text-bad">
            <ErrorIcon /> A few flagged changes still need your decision
          </p>
          <ul className="space-y-1 text-sm">
            {unresolved.map((b) => (
              <li key={b.id} className="flex flex-wrap gap-x-2">
                <code className="text-xs text-muted">{b.source_bullet_ids.join(", ")}</code>
                <span className="min-w-0 flex-1 truncate">{b.text}</span>
              </li>
            ))}
            {summaryUnresolved && <li>Your rewritten summary</li>}
          </ul>
          <Link href="/app/review" className="inline-block text-sm font-medium text-accent underline-offset-2 hover:underline">
            Resolve them on the review page
          </Link>
        </div>
      ) : (
        <p className="mt-3 flex items-center gap-2 text-sm text-ok">
          <CheckIcon />
          {approvedCount > 0
            ? `${approvedCount} approved change${approvedCount === 1 ? "" : "s"} included. Everything else is exactly as you wrote it.`
            : "No changes approved, so this is your original resume in a clean, ATS-friendly layout."}
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {(["docx", "pdf"] as const).map((fmt) => (
          <Button key={fmt} variant={fmt === "docx" ? "primary" : "secondary"} onClick={() => onDownload(fmt)}
            busy={busy === fmt} disabled={blocked || (busy !== null && busy !== fmt)}
            aria-describedby={blocked ? "export-blocked" : undefined}>
            <FileIcon /> Download {fmt.toUpperCase()}
          </Button>
        ))}
      </div>
      <p className="mt-3 text-xs text-muted">
        Single column, standard headings, no tables, icons, or images, so applicant tracking systems can read it.
        DOCX is the safest choice for most job sites.
      </p>
      <div aria-live="polite" className="mt-3">
        {downloaded && <Alert tone="ok" title="Downloaded">{downloaded}</Alert>}
        {error && <Alert tone="bad" role="alert" title="Download didn't finish">{error}</Alert>}
      </div>
    </section>
  );
}
