"use client";

import type { ATSReport, ScoreComponent } from "@/lib/schemas";

// Fixed order and wording, matching the scoring model.
export const COMPONENTS: { name: ScoreComponent["name"]; label: string; explain: string }[] = [
  { name: "required_keywords", label: "Required keywords", explain: "Skills the job lists as required that appear on your resume." },
  { name: "preferred_keywords", label: "Preferred keywords", explain: "Nice-to-have skills that appear on your resume." },
  { name: "semantic_relevance", label: "Semantic relevance", explain: "How well your bullets speak to each line of the job, even in different words." },
  { name: "title_seniority", label: "Title & seniority", explain: "How close your job titles and experience level are to the role." },
  { name: "format_parseability", label: "Format", explain: "Whether an ATS can read your resume cleanly: one column, standard headings, dated roles." },
  { name: "quantified_impact", label: "Quantified impact", explain: "How many of your bullets include a real number." },
];

export function BreakdownBars({ before, after }: { before: ATSReport; after: ATSReport | null }) {
  const find = (r: ATSReport | null, n: string) => r?.components.find((c) => c.name === n) ?? null;
  return (
    <ul className="space-y-3" aria-label="Score breakdown">
      {COMPONENTS.map(({ name, label, explain }) => {
        const b = find(before, name);
        const a = find(after, name);
        if (!b) return null;
        const shown = a ?? b;
        const max = Math.round(shown.weight * 100);
        const changed = a && Math.abs(a.points - b.points) >= 0.05;
        return (
          <li key={name} className="rounded-xl border border-border bg-surface p-4" data-testid={`component-${name}`}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="font-medium">
                {label} <span className="text-sm font-normal text-muted">· weight {max}%</span>
              </p>
              <p className="text-sm tabular-nums">
                {changed && <><span className="text-muted line-through">{b.points.toFixed(1)}</span>{" "}</>}
                <span className="font-semibold">{shown.points.toFixed(1)}</span>
                <span className="text-muted"> of {max} points</span>
                {changed && (
                  <span className={a!.points > b.points ? "text-ok" : "text-bad"}>
                    {" "}({a!.points > b.points ? "+" : ""}{(a!.points - b.points).toFixed(1)})
                  </span>
                )}
              </p>
            </div>
            <div aria-hidden className="relative mt-2 h-2.5 overflow-hidden rounded-full bg-surface-2">
              {a && <div className="absolute inset-y-0 left-0 rounded-full bg-border-strong" style={{ width: `${b.score * 100}%` }} />}
              <div className="absolute inset-y-0 left-0 rounded-full bg-accent transition-[width] duration-700"
                style={{ width: `${shown.score * 100}%`, opacity: a ? 0.9 : 1 }} />
            </div>
            <details className="mt-2 text-sm">
              <summary className="cursor-pointer select-none text-muted">
                What this measures{shown.deterministic ? "" : " (judged by Claude)"}
              </summary>
              <p className="mt-1 text-muted">{explain}</p>
              {shown.notes && <p className="mt-1">{shown.notes}</p>}
              {!["required_keywords", "preferred_keywords"].includes(name) && (shown.matched.length > 0 || shown.missing.length > 0) && (
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  <Detail title="Looks good" items={shown.matched} />
                  <Detail title="Could improve" items={shown.missing} />
                </div>
              )}
            </details>
          </li>
        );
      })}
    </ul>
  );
}

function Detail({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</p>
      {items.length ? <ul className="mt-1 list-disc space-y-0.5 pl-4">{items.map((i) => <li key={i}>{i}</li>)}</ul>
        : <p className="mt-1 text-muted">Nothing here.</p>}
    </div>
  );
}
