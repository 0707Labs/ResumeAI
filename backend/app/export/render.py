"""Export the final resume as DOCX or PDF.

ATS-safe layout on purpose: one column, no tables, no images, standard
headings, plain bullet paragraphs, dates as text.

Callers pass a Resume that has already been through apply_tailoring with
approved_only=True, so only verified, user-approved text reaches the file.
"""

import io
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.models import Entry, Resume


def _contact_line(resume: Resume) -> str:
    c = resume.contact
    return " | ".join(filter(None, [c.email, c.phone, c.location, *c.links]))


def _entry_header(e: Entry) -> tuple[str, str]:
    left = " — ".join(filter(None, [e.title, e.organization]))
    if e.location:
        left = f"{left}, {e.location}" if left else e.location
    dates = " – ".join(filter(None, [e.start_date, e.end_date]))
    return left, dates


def _sections(resume: Resume):
    """(heading, [(header_left, dates, [bullets])]) in resume order, skills last."""
    out = []
    if resume.summary:
        out.append(("Summary", [("", "", [])], resume.summary))
    for s in resume.sections:
        entries = [(*_entry_header(e), [b.text for b in e.bullets]) for e in s.entries]
        out.append((s.heading.title() if s.heading.isupper() else s.heading, entries, None))
    if resume.skills:
        out.append(("Skills", [("", "", [])], ", ".join(resume.skills)))
    return out


def to_docx(resume: Resume) -> bytes:
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)

    name = doc.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = name.add_run(resume.name or "")
    run.bold, run.font.size = True, Pt(18)
    contact = doc.add_paragraph(_contact_line(resume))
    contact.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for heading, entries, text in _sections(resume):
        h = doc.add_paragraph()
        r = h.add_run(heading.upper())
        r.bold, r.font.size = True, Pt(12)
        if text is not None:
            doc.add_paragraph(text)
            continue
        for left, dates, bullets in entries:
            if left or dates:
                p = doc.add_paragraph()
                p.add_run(left).bold = True
                if dates:
                    p.add_run(f"\t{dates}" if left else dates)
            for b in bullets:
                doc.add_paragraph(b, style="List Bullet")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _safe(text: str) -> str:
    # Built-in PDF fonts cover Latin-1 plus common punctuation; replace the rest
    # rather than render empty boxes.
    out = []
    for ch in text:
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            out.append("?")
    return escape("".join(out))


def to_pdf(resume: Resume) -> bytes:
    styles = {
        "name": ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=18, leading=22,
                               alignment=TA_CENTER),
        "contact": ParagraphStyle("contact", fontName="Helvetica", fontSize=9.5, leading=12,
                                  alignment=TA_CENTER),
        "h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11.5, leading=14,
                            spaceBefore=10, spaceAfter=3),
        "entry": ParagraphStyle("entry", fontName="Helvetica-Bold", fontSize=10, leading=13,
                                spaceBefore=4),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=13),
        "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=10, leading=13,
                                 leftIndent=12, bulletIndent=2),
    }
    story = [Paragraph(_safe(resume.name or ""), styles["name"]),
             Paragraph(_safe(_contact_line(resume)), styles["contact"])]
    for heading, entries, text in _sections(resume):
        story.append(Paragraph(_safe(heading.upper()), styles["h"]))
        if text is not None:
            story.append(Paragraph(_safe(text), styles["body"]))
            continue
        for left, dates, bullets in entries:
            if left or dates:
                header = _safe(left) + (f"  <font name='Helvetica'>{_safe(dates)}</font>"
                                        if dates else "")
                story.append(Paragraph(header, styles["entry"]))
            for b in bullets:
                story.append(Paragraph(_safe(b), styles["bullet"], bulletText="•"))
    story.append(Spacer(1, 4))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                      topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                      title=f"{resume.name or 'Resume'}").build(story)
    return buf.getvalue()
