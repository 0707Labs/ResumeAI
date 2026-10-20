import type { ScoreComponent } from "@/lib/schemas";

import { CheckIcon, ErrorIcon } from "./icons";

/** Matched vs missing keywords. Each chip has an icon and the group has a heading,
 * so found/missing doesn't depend on color. */
export function KeywordChips({ title, component }: { title: string; component: ScoreComponent | null }) {
  if (!component) return null;
  const { matched, missing } = component;
  return (
    <section aria-label={title} className="space-y-3">
      <h3 className="font-medium">{title}</h3>
      <ChipGroup label={`Found (${matched.length})`} items={matched} found />
      <ChipGroup label={`Missing (${missing.length})`} items={missing} found={false} />
      {component.notes && <p className="text-sm text-muted">{component.notes}</p>}
    </section>
  );
}

function ChipGroup({ label, items, found }: { label: string; items: string[]; found: boolean }) {
  const Icon = found ? CheckIcon : ErrorIcon;
  return (
    <div>
      <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">{label}</p>
      {items.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {items.map((k) => (
            <li key={k} className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-sm ${
              found ? "border-ok/30 bg-ok-bg text-ok" : "border-bad/30 bg-bad-bg text-bad"
            }`}>
              <Icon className="h-3.5 w-3.5" />
              <span className="sr-only">{found ? "Found: " : "Missing: "}</span>
              {k}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">{found ? "None yet." : "Nothing missing."}</p>
      )}
    </div>
  );
}
