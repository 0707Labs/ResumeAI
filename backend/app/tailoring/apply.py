"""Turn a TailoredResume back into a Resume (for re-scoring and export).

Only verified text ever lands in the output. For each tailored bullet:
- verified and not rejected by the user -> tailored text
- otherwise -> the original text of its source bullet(s)
With `approved_only=True` (export), a bullet must also be approved by the user.
"""

from app.models import (
    Bullet,
    Entry,
    ReviewStatus,
    Resume,
    Section,
    TailoredResume,
)


def _usable(b, approved_only: bool) -> bool:
    if b.verification is None or not b.verification.passed:
        return False
    if b.review == ReviewStatus.REJECTED:
        return False
    return b.review == ReviewStatus.APPROVED or not approved_only


def apply_tailoring(resume: Resume, tailored: TailoredResume, *,
                    approved_only: bool = False) -> Resume:
    texts_by_entry: dict[str, list[str]] = {}
    used_sources: set[str] = set()
    for b in tailored.bullets:
        entry = b.entry_id or (resume.entry_for_bullet(b.source_bullet_ids[0]).id
                               if b.source_bullet_ids and
                               resume.entry_for_bullet(b.source_bullet_ids[0]) else None)
        if entry is None:
            continue
        if _usable(b, approved_only):
            texts_by_entry.setdefault(entry, []).append(b.text)
            used_sources.update(b.source_bullet_ids)
        else:
            for sid in b.source_bullet_ids:
                src = resume.bullet_by_id(sid)
                if src and sid not in used_sources:
                    texts_by_entry.setdefault(entry, []).append(src.text)
                    used_sources.add(sid)

    sections: list[Section] = []
    for section in resume.sections:
        entries: list[Entry] = []
        for entry in section.entries:
            texts = texts_by_entry.get(entry.id)
            if texts is None:
                texts = [b.text for b in entry.bullets]
            # Originals the tailored set never mentioned are kept at the end.
            texts += [b.text for b in entry.bullets
                      if b.id not in used_sources and b.text not in texts
                      and entry.id in texts_by_entry]
            bullets = [Bullet(id=f"{entry.id}.b{i}", text=t) for i, t in enumerate(texts, 1)]
            entries.append(entry.model_copy(update={"bullets": bullets}))
        sections.append(section.model_copy(update={"entries": entries}))

    summary = resume.summary
    sv = tailored.summary_verification
    summary_ok = tailored.summary_review == ReviewStatus.APPROVED or (
        not approved_only and tailored.summary_review != ReviewStatus.REJECTED)
    if tailored.summary and sv is not None and sv.passed and summary_ok:
        summary = tailored.summary

    out = resume.model_copy(update={"sections": sections, "summary": summary})
    return out.model_copy(update={"raw_text": render_text(out)})


def render_text(resume: Resume) -> str:
    """Plain-text rendering in section order, as an ATS would read it."""
    c = resume.contact
    lines = [resume.name or "", " | ".join(filter(None, [c.email, c.phone, c.location,
                                                         *c.links]))]
    if resume.summary:
        lines += ["SUMMARY", resume.summary]
    for section in resume.sections:
        lines.append(section.heading.upper())
        for e in section.entries:
            dates = " – ".join(filter(None, [e.start_date, e.end_date]))
            header = " | ".join(filter(None, [e.title, e.organization, e.location, dates]))
            if header:
                lines.append(header)
            lines += [f"• {b.text}" for b in e.bullets]
    if resume.skills:
        lines += ["SKILLS", ", ".join(resume.skills)]
    return "\n".join(x for x in lines if x)
