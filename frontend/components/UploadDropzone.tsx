"use client";

import { useId, useRef, useState } from "react";

import { FileIcon, UploadIcon } from "./icons";
import { Spinner } from "./ui";

export const MAX_BYTES = 5 * 1024 * 1024;
const ACCEPT = {
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
} as const;

/** Client-side check before uploading. Returns a friendly reason, or null if OK. */
export function checkFile(file: File): string | null {
  const name = file.name.toLowerCase();
  const okExt = Object.keys(ACCEPT).some((ext) => name.endsWith(ext));
  if (!okExt) {
    return `"${file.name}" isn't a PDF or DOCX. Please upload one of those, or paste your resume as text.`;
  }
  if (file.size > MAX_BYTES) return `"${file.name}" is over 5 MB. Try a smaller export, or paste the text instead.`;
  if (file.size === 0) return `"${file.name}" is empty.`;
  return null;
}

export function UploadDropzone({ onFile, onReject, busy = false, fileName }: {
  onFile: (file: File) => void;
  onReject: (message: string) => void;
  busy?: boolean;
  fileName?: string | null;
}) {
  const input = useRef<HTMLInputElement>(null);
  const helpId = useId();
  const [dragging, setDragging] = useState(false);

  const take = (file: File | undefined) => {
    if (!file || busy) return;
    const problem = checkFile(file);
    if (problem) onReject(problem);
    else onFile(file);
  };

  return (
    <div
      onDragEnter={(e) => { e.preventDefault(); setDragging(true); }}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
      onDrop={(e) => { e.preventDefault(); setDragging(false); take(e.dataTransfer.files[0]); }}
      data-testid="dropzone"
      className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors ${
        dragging ? "border-accent bg-accent-soft" : "border-border-strong bg-surface-2/40"
      }`}
    >
      {busy ? <Spinner /> : fileName ? <FileIcon className="h-6 w-6 text-accent" /> : <UploadIcon className="h-6 w-6 text-muted" />}
      <p className="text-sm text-fg">
        {busy ? "Reading your resume…" : fileName ? <>Loaded <span className="font-medium">{fileName}</span></> : "Drag your resume here"}
      </p>
      <button
        type="button"
        onClick={() => input.current?.click()}
        disabled={busy}
        aria-describedby={helpId}
        className="rounded-lg border border-border-strong bg-surface px-4 py-2 text-sm font-medium text-fg hover:bg-surface-2 disabled:opacity-50"
      >
        {fileName ? "Choose a different file" : "Choose a file"}
      </button>
      <p id={helpId} className="text-xs text-muted">PDF or DOCX, up to 5 MB</p>
      <input
        ref={input}
        type="file"
        accept={Object.entries(ACCEPT).flat().join(",")}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="file-input"
        onChange={(e) => { take(e.target.files?.[0]); e.target.value = ""; }}
      />
    </div>
  );
}
