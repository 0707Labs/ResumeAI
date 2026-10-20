"use client";

import type { Resume } from "@/lib/schemas";

import { AlertIcon, CheckIcon } from "./icons";

/** What we read from the resume, so the user can catch parsing mistakes early. */
export function ResumePreview({ resume, onPasteInstead }: { resume: Resume; onPasteInstead: () => void }) {
  const bullets = resume.sections.flatMap((s) => s.entries.flatMap((e) => e.bullets));
  const roles = resume.sections.filter((s) => s.kind === "experience").flatMap((s) => s.entries);

  return (
    <div className="mt-4 rounded-xl border border-border bg-surface-2/50 p-4">
      <p className="flex items-center gap-2 text-sm font-medium text-ok">
        <CheckIcon /> Here&apos;s what we read
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
        <Stat label="Name" value={resume.name ?? "Not found"} />
        <Stat label="Roles" value={String(roles.length)} />
        <Stat label="Bullets" value={String(bullets.length)} />
        <Stat label="Skills" value={String(resume.skills.length)} />
      </dl>

      {resume.parse_warnings.length > 0 && (
        <ul className="mt-3 space-y-1" aria-label="Formatting notes">
          {resume.parse_warnings.map((w) => (
            <li key={w.code} className="flex gap-2 text-sm text-warn">
              <AlertIcon className="mt-0.5 h-4 w-4" />
              <span><span className="font-medium">Heads up:</span> {w.message}</span>
            </li>
          ))}
        </ul>
      )}

      <details className="mt-3 group">
        <summary className="cursor-pointer text-sm font-medium text-accent hover:underline">
          Show each bullet and its ID
        </summary>
        <div className="mt-3 max-h-80 space-y-3 overflow-y-auto pr-1">
          {resume.sections.map((s) => (
            <div key={s.heading}>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">{s.heading}</h4>
              {s.entries.map((e) => (
                <div key={e.id} className="mt-1.5">
                  {(e.title || e.organization) && (
                    <p className="text-sm font-medium">{[e.title, e.organization].filter(Boolean).join(" · ")}</p>
                  )}
                  <ul className="mt-1 space-y-1">
                    {e.bullets.map((b) => (
                      <li key={b.id} className="flex gap-2 text-sm">
                        <code className="shrink-0 rounded bg-surface px-1 text-xs text-muted">{b.id}</code>
                        <span>{b.text}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ))}
        </div>
      </details>

      <p className="mt-3 text-sm text-muted">
        Something look off?{" "}
        <button type="button" onClick={onPasteInstead} className="font-medium text-accent underline-offset-2 hover:underline">
          Paste the text instead
        </button>
        . You can edit what we read before analyzing.
      </p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="truncate font-medium">{value}</dd>
    </div>
  );
}
