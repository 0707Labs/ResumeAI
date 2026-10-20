"use client";

import { useRef, useState } from "react";

import type { Resume } from "@/lib/types";

import { Button, Card, Note, Pill } from "./ui";

export function ResumeStep({ resume, busy, onFile, onSample }: {
  resume: Resume | null;
  busy: boolean;
  onFile: (file: File) => void;
  onSample: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  return (
    <div className="space-y-5">
      <Card title="1. Upload your resume" actions={<Button variant="ghost" onClick={onSample} disabled={busy}>Use the sample resume and JD</Button>}>
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const f = e.dataTransfer.files[0];
            if (f) onFile(f);
          }}
          className={`flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-10 text-center transition-colors ${dragging ? "border-slate-900 bg-slate-50" : "border-slate-300"}`}
        >
          <p className="text-sm text-slate-600">Drop a PDF, DOCX, or TXT file here (max 5 MB)</p>
          <Button variant="secondary" busy={busy} onClick={() => input.current?.click()}>Choose file</Button>
          <input
            ref={input}
            type="file"
            accept=".pdf,.docx,.txt"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onFile(f);
              e.target.value = "";
            }}
          />
        </div>
        <Note>Parsing runs on your backend. Nothing is rewritten at this step; each bullet just gets a stable ID.</Note>
      </Card>

      {resume && <ParsedResume resume={resume} />}
    </div>
  );
}

function ParsedResume({ resume }: { resume: Resume }) {
  const bullets = resume.sections.flatMap((s) => s.entries.flatMap((e) => e.bullets));
  return (
    <Card title={<>Parsed: {resume.name ?? "name not found"}</>} actions={<Pill tone="slate">{bullets.length} bullets</Pill>}>
      {resume.parse_warnings.length > 0 && (
        <ul className="mb-4 space-y-1 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          {resume.parse_warnings.map((w) => <li key={w.code}>⚠ {w.message}</li>)}
        </ul>
      )}
      <p className="mb-3 text-sm text-slate-600">
        {[resume.contact.email, resume.contact.phone, resume.contact.location].filter(Boolean).join(" · ")}
      </p>
      {resume.skills.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-1.5">
          {resume.skills.map((s) => <Pill key={s}>{s}</Pill>)}
        </div>
      )}
      <div className="space-y-4">
        {resume.sections.map((s) => (
          <div key={s.heading}>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{s.heading}</h3>
            {s.entries.map((e) => (
              <div key={e.id} className="mb-2">
                <p className="text-sm font-medium text-slate-800">
                  {[e.title, e.organization].filter(Boolean).join(" — ") || <span className="text-slate-400">(no header)</span>}
                  {(e.start_date || e.end_date) && (
                    <span className="ml-2 font-normal text-slate-500">{[e.start_date, e.end_date].filter(Boolean).join(" – ")}</span>
                  )}
                </p>
                <ul className="mt-1 space-y-0.5">
                  {e.bullets.map((b) => (
                    <li key={b.id} className="flex gap-2 text-sm text-slate-700">
                      <code className="shrink-0 text-xs text-slate-400">{b.id}</code>
                      <span>{b.text}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ))}
      </div>
    </Card>
  );
}
