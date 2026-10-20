"""Build PDF/DOCX resumes at test time so no binary fixtures live in git.

Database tests get a throwaway Postgres database per run (migrated with Alembic)
and a per-test transaction that is rolled back."""

import io
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from docx import Document
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

FIXTURES = Path(__file__).parent / "fixtures"
BACKEND = Path(__file__).parent.parent
# A server we may create and drop databases on; the local socket by default.
ADMIN_URL = os.environ.get("RT_TEST_ADMIN_DATABASE_URL", "postgresql+psycopg:///postgres")


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text()


def make_pdf(rows: list[tuple], *, blank: bool = False) -> bytes:
    """rows: (x, text) for left text, or (x, text, right_text) for a right-aligned
    date on the same line. One row per line, top to bottom."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    width, height = LETTER
    if not blank:
        y = height - 60
        c.setFont("Helvetica", 10)
        for row in rows:
            c.drawString(row[0], y, row[1])
            if len(row) > 2:
                c.drawRightString(width - 50, y, row[2])
            y -= 14
    else:
        c.rect(50, 50, 100, 100)  # a drawing with no text, like a scanned page
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture
def analyst_pdf() -> bytes:
    L, B, W = 50, 60, 68  # left margin, bullet glyph x, wrapped-text x
    return make_pdf([
        (L, "Ravi Menon"),
        (L, "ravi.menon@example.com | +1 415 555 0134 | github.com/ravimenon"),
        (L, "EXPERIENCE"),
        (L, "Software Engineer | Globex Corporation", "Mar 2021 – Present"),
        (B, "• Contributed to migrating billing services from a monolith to"),
        (W, "microservices in Java and Spring Boot"),
        (B, "• Reduced p95 API latency by 40% by adding Redis caching"),
        (L, "Software Engineering Intern | Initech", "Jun 2020 – Aug 2020"),
        (B, "• Wrote unit tests for the payments module with JUnit"),
        (L, "EDUCATION"),
        (L, "B.S. Computer Science, University of Washington", "2016 – 2020"),
        (L, "SKILLS"),
        (L, "Java, Python, SQL, Docker, Redis"),
    ])


@pytest.fixture
def two_column_pdf() -> bytes:
    rows = [(50, "Priya Shah")]
    for i in range(10):
        rows.append((50, f"Left column sentence number {i} here", f"right column words {i} here"))
    return make_pdf(rows)


@pytest.fixture
def blank_pdf() -> bytes:
    return make_pdf([], blank=True)


@pytest.fixture
def analyst_docx() -> bytes:
    doc = Document()
    doc.add_paragraph("Meera Iyer", style="Title")
    doc.add_paragraph("meera.iyer@example.com | +44 20 7946 0958")
    doc.add_paragraph("Professional Experience", style="Heading 1")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Marketing Analyst, Contoso Ltd"
    table.rows[0].cells[1].text = "Feb 2019 – Present"
    doc.add_paragraph("Helped run weekly campaign reporting in Excel", style="List Bullet")
    doc.add_paragraph("Grew newsletter signups 25% through A/B tests on subject lines",
                      style="List Bullet")
    doc.add_paragraph("Product Analyst\tJan 2017 – Jan 2019")
    doc.add_paragraph("Fabrikam Inc")
    doc.add_paragraph("Assisted with SQL queries for the quarterly churn review",
                      style="List Bullet")
    doc.add_paragraph("Education", style="Heading 1")
    doc.add_paragraph("MBA, London Business School, 2016")
    doc.add_paragraph("Skills", style="Heading 1")
    doc.add_paragraph("Excel; SQL; Google Analytics; Tableau")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def pg_url() -> str:
    """URL of a fresh database migrated to head; dropped after the run.
    Skips DB tests when no Postgres is reachable, except in CI where that fails."""
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    name = f"rt_test_{uuid.uuid4().hex[:8]}"
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # noqa: BLE001 - any connection failure means "no Postgres here"
        admin.dispose()
        if os.environ.get("CI"):
            raise
        pytest.skip(f"Postgres not reachable at {ADMIN_URL}: {exc.__class__.__name__}")
    url = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    try:
        command.upgrade(alembic_config(url), "head")
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="session")
def pg_engine(pg_url):
    engine = create_engine(pg_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(pg_engine):
    """A Session inside one outer transaction that is rolled back after the test.
    Commits inside the test become savepoints."""
    with pg_engine.connect() as conn:
        outer = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            outer.rollback()
