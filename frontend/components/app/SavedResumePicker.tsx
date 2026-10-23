"use client";

import { useEffect, useId, useState } from "react";

import { Button, inlineInputClass } from "@/components/ui";
import type { Resume, ResumeSummary } from "@/lib/schemas";
import { userApi, userError } from "@/lib/user";

/** On the tailoring input: start from a saved base resume instead of uploading again.
 * Shows nothing without saved resumes (or when they can't be loaded). */
export function SavedResumePicker({ onPick, disabled }: { onPick: (resume: Resume, title: string) => void; disabled?: boolean }) {
  const id = useId();
  const [list, setList] = useState<ResumeSummary[]>([]);
  const [chosen, setChosen] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    userApi.resumes().then((l) => { setList(l); setChosen(l.find((r) => r.is_default)?.id ?? l[0]?.id ?? ""); }).catch(() => {});
  }, []);
  if (list.length === 0) return null;

  async function use() {
    setBusy(true);
    setError(null);
    try {
      const d = await userApi.resume(chosen);
      onPick(d.resume, d.title);
    } catch (e) {
      setError(userError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 rounded-xl border border-border bg-surface-2/40 p-3">
      <label htmlFor={id} className="text-sm font-medium text-fg">Use a saved resume</label>
      <div className="mt-1.5 flex flex-wrap gap-2">
        <select id={id} className={`${inlineInputClass} min-w-0 flex-1`} value={chosen} onChange={(e) => setChosen(e.target.value)}>
          {list.map((r) => <option key={r.id} value={r.id}>{r.title}{r.is_default ? " (default)" : ""}</option>)}
        </select>
        <Button variant="secondary" busy={busy} disabled={disabled || !chosen} onClick={use}>Use it</Button>
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
    </div>
  );
}
