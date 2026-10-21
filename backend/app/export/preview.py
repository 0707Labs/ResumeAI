"""The pre-payment preview: the exact file, as low-resolution images with the protection
baked in on the server.

render_preview() builds the same PDF a download would contain, rasterizes it at
PREVIEW_DPI, blurs the contact line and the last section, optionally tints changed lines,
and tiles a diagonal "PREVIEW - 0707Labs" watermark over every page. The browser only
ever gets PNGs: no selectable text, nothing under a CSS blur to unblur. This deters
copying; it can't stop a screenshot (see docs/protection.md).
"""

import base64
import io
import math
import re
import threading
from dataclasses import dataclass

import pdfplumber
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.export.render import _contact_line, _sections, to_pdf
from app.models import Resume

PREVIEW_DPI = 60  # about 510 x 660 px for a Letter page: readable, poor for reuse
WATERMARK = "PREVIEW - 0707Labs"
BLUR_RADIUS = 7

# PDFium (behind pdfplumber's page images) isn't thread-safe, and routes run this in a
# threadpool: two previews rasterizing at once can crash the process. One at a time.
_PDFIUM = threading.Lock()


@dataclass(frozen=True)
class PreviewPage:
    png: bytes
    width: int
    height: int

    def data_url(self) -> str:
        return "data:image/png;base64," + base64.b64encode(self.png).decode()


@dataclass(frozen=True)
class Preview:
    pages: list[PreviewPage]
    masked: list[str]  # what was blurred, in words, for the page to say
    changed_marked: int  # changed lines tinted on the images


def _norm(text: str) -> str:
    text = re.sub(r"\(cid:\d+\)", " ", text)  # the bullet glyph, as pdfplumber reports it
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _blur(img: Image.Image, box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = (max(0, box[0]), max(0, box[1]), min(img.width, box[2]), min(img.height, box[3]))
    if x1 > x0 and y1 > y0:
        region = img.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
        img.paste(region, (x0, y0))


def _watermark(img: Image.Image) -> Image.Image:
    """Tile the watermark diagonally across the whole page, semi-opaque, baked in."""
    size = max(14, img.width // 18)
    font = ImageFont.load_default(size=size)
    tile_w = int(font.getlength(WATERMARK)) + size * 3
    diag = int(math.hypot(img.width, img.height))
    layer = Image.new("RGBA", (diag * 2, diag * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for row, y in enumerate(range(0, diag * 2, size * 4)):
        offset = (row % 2) * tile_w // 2
        for x in range(-tile_w, diag * 2, tile_w):
            draw.text((x + offset, y), WATERMARK, font=font, fill=(120, 120, 120, 90))
    layer = layer.rotate(35, resample=Image.Resampling.BICUBIC)
    left, top = (layer.width - img.width) // 2, (layer.height - img.height) // 2
    layer = layer.crop((left, top, left + img.width, top + img.height))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def render_preview(resume: Resume, changed_lines: list[str] = (), *, mark_changes: bool = False) -> Preview:
    pdf = to_pdf(resume)
    scale = PREVIEW_DPI / 72
    contact = _norm(_contact_line(resume))
    name = _norm(resume.name or "")
    sections = _sections(resume)
    last_heading = _norm(sections[-1][0]) if sections else ""
    changed = [_norm(t)[:40] for t in changed_lines if _norm(t)]

    pages, masked, marked = [], [], 0
    blur_rest = False  # once the last section starts, everything after it is blurred
    with _PDFIUM, pdfplumber.open(io.BytesIO(pdf)) as doc:
        for page in doc.pages:
            img = page.to_image(resolution=PREVIEW_DPI).original.convert("RGB")
            tint = ImageDraw.Draw(img, "RGBA")
            lines = page.extract_text_lines()
            for line in lines:
                text = _norm(line["text"])
                box = (int(line["x0"] * scale) - 3, int(line["top"] * scale) - 2,
                       int(line["x1"] * scale) + 3, int(line["bottom"] * scale) + 2)
                if not blur_rest and last_heading and text == last_heading:
                    blur_rest = True
                if blur_rest:
                    _blur(img, (0, box[1], img.width, box[3]))
                    continue
                if contact and len(text) > 6 and text != name and (text in contact or contact in text):
                    _blur(img, (0, box[1], img.width, box[3]))
                    continue
                if mark_changes and changed and any(c and (text.startswith(c[:30]) or c.startswith(text[:30]))
                                                    for c in changed):
                    tint.rectangle(box, fill=(255, 196, 0, 60))
                    marked += 1
            img = _watermark(img)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            pages.append(PreviewPage(buf.getvalue(), img.width, img.height))
    if contact:
        masked.append("contact details")
    if last_heading and blur_rest:
        masked.append(f"the {sections[-1][0]} section")
    return Preview(pages, masked, marked)
