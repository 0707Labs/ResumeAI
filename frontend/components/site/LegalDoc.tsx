import type { ReactNode } from "react";

import { Alert } from "@/components/ui";

/**
 * A legal page: title, version date and numbered sections. DRAFT until counsel
 * signs off; flip `draft` off per page once the text is final.
 */
export function LegalDoc({ title, updated, draft = true, intro, sections }: {
  title: string;
  updated: string;
  draft?: boolean;
  intro?: ReactNode;
  sections: { heading: string; body: ReactNode }[];
}) {
  return (
    <article className="mx-auto max-w-3xl px-4 py-12 sm:px-6 sm:py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 text-sm text-muted">Last updated {updated}</p>
      {draft && (
        <div className="mt-6">
          <Alert tone="warn" title="Draft">
            This text is a draft that hasn&apos;t been reviewed by a lawyer yet. It may change before launch.
          </Alert>
        </div>
      )}
      {intro && <div className="mt-6 space-y-3 leading-7">{intro}</div>}
      <ol className="mt-8 space-y-8">
        {sections.map(({ heading, body }, i) => (
          <li key={heading}>
            <h2 className="text-lg font-semibold">{i + 1}. {heading}</h2>
            <div className="mt-2 space-y-3 leading-7 text-fg [&_a]:text-accent [&_a]:underline [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-5">
              {body}
            </div>
          </li>
        ))}
      </ol>
    </article>
  );
}
