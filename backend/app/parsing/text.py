"""Line-level helpers shared by the resume and JD parsers."""

import re
from dataclasses import dataclass, field

# "•", "▪", "➢", "-", "*", "1." etc. Private-use glyphs (Symbol/Wingdings bullets
# in PDFs) are normalized to "•" during extraction.
BULLET_RE = re.compile(r"^\s*(?:[•●○◦▪▫■□‣⁃∙·➢➤►▶✓✔❖◆◇–—\-*]|\(?\d{1,2}[.)])\s+")

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_DATE = rf"(?:{_MONTH}\s*'?\d{{2,4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
_OPEN_END = r"(?:present|current|now|ongoing|till date|to date)"
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE})\s*(?:-|–|—|to|until)\s*(?P<end>{_DATE}|{_OPEN_END})", re.IGNORECASE
)
SINGLE_DATE_RE = re.compile(rf"(?:{_MONTH}\s*\d{{4}}|\b(?:19|20)\d{{2}}\b)", re.IGNORECASE)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
URL_RE = re.compile(
    r"(?<![\w@.])(?:https?://)?(?:www\.)?"
    r"(?:linkedin\.com|github\.com|gitlab\.com|[\w-]+\.(?:dev|io|me)\b)(?!@)"
    r"/?[\w\-./]*",
    re.IGNORECASE,
)


@dataclass
class Line:
    text: str
    # Pieces separated by a wide horizontal gap in a PDF, or by table cells in a
    # DOCX; e.g. ["Acme Corp", "Jan 2020 – Present"]. Single-item when unknown.
    segments: list[str] = field(default_factory=list)
    x0: float | None = None  # left edge in points (PDF only)
    is_list_item: bool = False  # DOCX list paragraph with no visible glyph

    def __post_init__(self) -> None:
        self.text = normalize_space(self.text)
        self.segments = [normalize_space(s) for s in self.segments if s.strip()] or [self.text]


def normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace(" ", " ")).strip()


def strip_bullet(text: str) -> tuple[bool, str]:
    m = BULLET_RE.match(text)
    if not m:
        return False, text
    return True, text[m.end():].strip()


def join_wrapped(prev: str, nxt: str) -> str:
    """Join a bullet with its wrapped continuation line."""
    if prev.endswith("-") and nxt[:1].islower() and not prev.endswith(" -"):
        return prev + nxt  # "data-" + "driven" -> "data-driven"
    return f"{prev} {nxt}"


def has_date(text: str) -> bool:
    return bool(DATE_RANGE_RE.search(text) or SINGLE_DATE_RE.search(text))


def is_contact_line(text: str) -> bool:
    if not (EMAIL_RE.search(text) or PHONE_RE.search(text) or URL_RE.search(text)):
        return False
    rest = PHONE_RE.sub("", URL_RE.sub("", EMAIL_RE.sub("", text)))
    # Mostly contact tokens and separators, e.g. "a@b.com | +91 98xx | linkedin.com/in/a"
    return len(re.findall(r"[A-Za-z]{3,}", rest)) <= 4
