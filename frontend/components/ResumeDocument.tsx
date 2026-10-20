import type { Resume } from "@/lib/schemas";

/**
 * On-screen preview laid out like the exported file: one column, standard
 * headings, plain bullets, no tables, icons, or images. Always a light "page",
 * even in dark mode, because that's what the file will look like.
 */
export function ResumeDocument({ resume, changed, markChanges }: {
  resume: Resume;
  changed: Set<string>;
  markChanges: boolean;
}) {
  const c = resume.contact;
  const contact = [c.email, c.phone, c.location, ...c.links].filter(Boolean).join(" | ");
  const line = (text: string) =>
    markChanges && changed.has(text) ? (
      <span className="rounded bg-[#e5efef] px-1 box-decoration-clone" data-changed="true">
        <span className="sr-only">Changed line: </span>{text}
        <span aria-hidden className="ml-1.5 rounded bg-[#2f5d62] px-1 align-middle text-[10px] font-semibold uppercase tracking-wide text-white">changed</span>
      </span>
    ) : text;

  return (
    <article
      aria-label="Preview of your exported resume"
      className="mx-auto max-w-[8.5in] rounded-md bg-white px-6 py-8 text-[13px] leading-relaxed text-[#111] shadow-sm ring-1 ring-black/10 sm:px-12"
      style={{ colorScheme: "light", fontFamily: "Calibri, Carlito, 'Segoe UI', Arial, sans-serif" }}
      data-testid="resume-document"
    >
      <header className="text-center">
        <h2 className="text-2xl font-bold">{resume.name ?? ""}</h2>
        {contact && <p className="mt-1 text-[#333]">{contact}</p>}
      </header>

      {resume.summary && (
        <Section title="Summary">
          <p>{line(resume.summary)}</p>
        </Section>
      )}

      {resume.sections.map((s) => (
        <Section key={s.heading} title={s.heading}>
          {s.entries.map((e) => {
            const left = [e.title, e.organization].filter(Boolean).join(" — ") + (e.location ? `, ${e.location}` : "");
            const dates = [e.start_date, e.end_date].filter(Boolean).join(" – ");
            return (
              <div key={e.id} className="mt-2">
                {(left || dates) && (
                  <p className="flex flex-wrap justify-between gap-x-4">
                    <span className="font-bold">{left}</span>
                    {dates && <span>{dates}</span>}
                  </p>
                )}
                {e.bullets.length > 0 && (
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {e.bullets.map((b) => <li key={b.id}>{line(b.text)}</li>)}
                  </ul>
                )}
              </div>
            );
          })}
        </Section>
      ))}

      {resume.skills.length > 0 && (
        <Section title="Skills">
          <p>{resume.skills.join(", ")}</p>
        </Section>
      )}
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <h3 className="border-b border-[#ccc] pb-0.5 text-[14px] font-bold uppercase tracking-wide">{title}</h3>
      <div className="mt-1.5">{children}</div>
    </section>
  );
}
