import { CheckIcon } from "@/components/icons";

/** Made-up resume lines for the hero. Each tailored line cites the bullet it came from. */
export const HERO_ROWS = [
  {
    id: "b5",
    change: "Moved up",
    before: "Wrote dbt models for the weekly revenue report.",
    after: "Wrote dbt models for the weekly revenue report.",
  },
  {
    id: "b3",
    change: "Reworded",
    before: "Worked on dashboards for the sales team using SQL and Tableau.",
    after: "Built SQL and Tableau dashboards for the sales team.",
  },
  {
    id: "b2",
    change: "Result first",
    before: "Rewrote slow report queries; refresh time went from 40 to 12 minutes.",
    after: "Cut report refresh time from 40 to 12 minutes by rewriting slow queries.",
  },
] as const;

/**
 * The hero's before/after: the original resume beside the tailored one, each pair joined by a
 * dashed seam that carries the source bullet's id. Real list markup, so it reads in order
 * without the picture. Side by side from sm up; stacked with a vertical seam on phones.
 */
export function BeforeAfter() {
  return (
    <figure aria-labelledby="before-after-caption" className="w-full min-w-0">
      <div className="overflow-hidden rounded-hero border border-border bg-surface shadow-[0_24px_48px_-24px_rgb(11_26_58/0.25)]">
        <div className="hidden grid-cols-[1fr_4.5rem_1fr] border-b border-border bg-surface-2 text-xs font-medium text-muted sm:grid">
          <p className="px-4 py-2.5">Your resume</p>
          <span />
          <p className="px-4 py-2.5">Tailored for Analytics Engineer</p>
        </div>
        <ol className="divide-y divide-border">
          {HERO_ROWS.map((row) => (
            <li key={row.id} className="grid gap-0 p-4 sm:grid-cols-[1fr_4.5rem_1fr] sm:items-center sm:p-0">
              <p className="text-sm text-muted sm:px-4 sm:py-4">
                <span className="mb-1 block text-xs font-medium sm:hidden">Your resume</span>
                <span className="sr-only">Before: </span>{row.before}
              </p>
              <Seam id={row.id} />
              <p className="text-sm font-medium text-fg sm:px-4 sm:py-4">
                <span className="mb-1 block text-xs font-medium text-muted sm:hidden">Tailored</span>
                <span className="sr-only">After ({row.change.toLowerCase()}, cites {row.id}): </span>{row.after}
                <span aria-hidden="true" className="mt-1.5 block text-xs font-normal text-accent">{row.change}</span>
              </p>
            </li>
          ))}
        </ol>
        <p className="flex items-center gap-2 border-t border-border bg-ok-bg px-4 py-3 text-sm font-medium text-ok">
          <CheckIcon />
          Verified: every line traces to your resume. No new claims.
        </p>
      </div>
      <figcaption id="before-after-caption" className="mt-3 text-center text-xs text-muted">
        Sample data. Each tailored line keeps the id of the bullet it came from.
      </figcaption>
    </figure>
  );
}

/** The dashed stitch with the source id riding on it: horizontal beside, vertical when stacked. */
function Seam({ id }: { id: string }) {
  return (
    <span aria-hidden="true" className="relative flex h-10 items-center justify-start pl-3 sm:h-full sm:justify-center sm:pl-0">
      <span className="absolute inset-y-0 left-6 border-l-2 border-dashed border-seam sm:inset-x-0 sm:inset-y-auto sm:left-0 sm:top-1/2 sm:border-l-0 sm:border-t-2" />
      <span className="relative rounded-md border border-seam bg-surface px-1.5 py-0.5 font-mono text-[11px] leading-none text-accent">
        {id}
      </span>
    </span>
  );
}
