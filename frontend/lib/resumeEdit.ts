/**
 * Editing a saved resume without breaking what points at it. Bullet ids are stable
 * handles (tailored bullets cite them as source_bullet_ids), so existing ids never change;
 * new bullets get "<entry id>.b<next n>" and new entries "<prefix><next n>", the same
 * shapes the parser makes (backend app/models/resume.py ID_PATTERN).
 */
import type * as S from "./schemas";

type Resume = S.Resume;
type Entry = Resume["sections"][number]["entries"][number];
type Kind = Resume["sections"][number]["kind"];

const PREFIX: Record<Kind, string> = { experience: "exp", projects: "proj", education: "edu", certifications: "cert", other: "item" };

export function nextBulletId(entry: Entry): string {
  const ns = entry.bullets.map((b) => Number(/\.b(\d+)$/.exec(b.id)?.[1] ?? 0));
  return `${entry.id}.b${Math.max(0, ...ns) + 1}`;
}

export function nextEntryId(resume: Resume, kind: Kind): string {
  const prefix = PREFIX[kind];
  const ns = resume.sections.flatMap((s) => s.entries)
    .map((e) => new RegExp(`^${prefix}(\\d+)$`).exec(e.id)?.[1]).filter(Boolean).map(Number);
  return `${prefix}${Math.max(0, ...ns) + 1}`;
}

export function blankEntry(resume: Resume, kind: Kind): Entry {
  return { id: nextEntryId(resume, kind), title: "", organization: null, location: null, start_date: null,
    end_date: null, bullets: [] };
}

const blankToNull = (v: string | null) => (v && v.trim() ? v.trim() : null);

/** What gets saved: trimmed fields, empty bullets dropped, raw_text rebuilt from the
 * edited content so scoring reads what the resume now says. */
export function cleanForSave(resume: Resume): Resume {
  const sections = resume.sections.map((s) => ({
    ...s,
    heading: s.heading.trim() || s.heading,
    entries: s.entries.map((e) => ({
      ...e,
      title: blankToNull(e.title), organization: blankToNull(e.organization), location: blankToNull(e.location),
      start_date: blankToNull(e.start_date), end_date: blankToNull(e.end_date),
      bullets: e.bullets.map((b) => ({ ...b, text: b.text.trim() })).filter((b) => b.text),
    })),
  }));
  const next = { ...resume, summary: blankToNull(resume.summary), skills: resume.skills.map((x) => x.trim()).filter(Boolean), sections };
  return { ...next, raw_text: plainText(next) };
}

export function plainText(r: Resume): string {
  const lines: string[] = [];
  if (r.name) lines.push(r.name);
  const contact = [r.contact.email, r.contact.phone, r.contact.location, ...r.contact.links].filter(Boolean);
  if (contact.length) lines.push(contact.join(" | "));
  if (r.summary) lines.push("", "Summary", r.summary);
  if (r.skills.length) lines.push("", "Skills", r.skills.join(", "));
  for (const s of r.sections) {
    lines.push("", s.heading);
    for (const e of s.entries) {
      const head = [e.title, e.organization, e.location].filter(Boolean).join(", ");
      const dates = [e.start_date, e.end_date].filter(Boolean).join(" - ");
      lines.push([head, dates].filter(Boolean).join(" | "));
      for (const b of e.bullets) lines.push(`- ${b.text}`);
    }
  }
  return lines.join("\n").trim();
}

export const sameResume = (a: Resume, b: Resume) => JSON.stringify(cleanForSave(a)) === JSON.stringify(cleanForSave(b));
