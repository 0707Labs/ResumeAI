"use client";

import type { JobDescription } from "@/lib/types";

import { Button, Card, Pill } from "./ui";

export function JobStep({ text, setText, jd, busy, onParse }: {
  text: string;
  setText: (t: string) => void;
  jd: JobDescription | null;
  busy: boolean;
  onParse: () => void;
}) {
  return (
    <div className="space-y-5">
      <Card title="2. Paste the job description" actions={
        <Button onClick={onParse} busy={busy} disabled={text.trim().length < 20}>Parse JD</Button>
      }>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste the full job posting, including the requirements section…"
          rows={14}
          className="w-full rounded-lg border border-slate-300 p-3 font-mono text-sm focus:border-slate-900 focus:outline-none"
        />
      </Card>
      {jd && (
        <Card title={<>{jd.title ?? "Untitled role"}{jd.company && <span className="font-normal text-slate-500"> at {jd.company}</span>}</>}
          actions={<><Pill tone="blue">{jd.seniority}</Pill>{jd.years_experience_min != null && <Pill>{jd.years_experience_min}+ years</Pill>}</>}>
          <div className="grid gap-5 md:grid-cols-2">
            <ReqList title="Required" reqs={jd.requirements.filter((r) => r.priority === "required")} />
            <ReqList title="Preferred" reqs={jd.requirements.filter((r) => r.priority === "preferred")} />
          </div>
        </Card>
      )}
    </div>
  );
}

function ReqList({ title, reqs }: { title: string; reqs: JobDescription["requirements"] }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title} ({reqs.length})</h3>
      <ul className="space-y-2">
        {reqs.map((r) => (
          <li key={r.id} className="text-sm text-slate-700">
            <span>{r.text}</span>
            {r.keywords.length > 0 && (
              <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">
                {r.keywords.map((k) => <Pill key={k} tone="violet">{k}</Pill>)}
              </span>
            )}
          </li>
        ))}
        {reqs.length === 0 && <li className="text-sm text-slate-400">None found</li>}
      </ul>
    </div>
  );
}
