"""Rebuild the favicon and logo assets from brand/logo-source.webp.

Run from frontend/ with any Python that has Pillow:
    python brand/make_brand.py brand/logo-source.webp
"""
import sys
from PIL import Image, ImageDraw, ImageFilter

src = Image.open(sys.argv[1]).convert("RGBA")
w, h = src.size
work = src.copy()
d = ImageDraw.Draw(work)
red = (255, 0, 0, 255)
# The paper is the same white as the background in two places; wall those off so
# the flood fill from the corners only clears the real background.
d.line([(400, 728), (430, 740), (452, 748), (458, 764), (480, 778), (497, 792)], fill=red, width=3)
d.line([(744, 384), (886, 392)], fill=red, width=3)
for c in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
    ImageDraw.floodfill(work, c, (0, 0, 0, 0), thresh=40)
alpha = work.getchannel("A").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.7))
out = src.copy()
out.putalpha(alpha)

top = out.crop((0, 0, w, int(h * 0.68)))
mark = top.crop(top.getbbox())
side = max(mark.size)
pad = int(side * 0.04)
sq = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
sq.paste(mark, ((sq.width - mark.width) // 2, (sq.height - mark.height) // 2), mark)
sq.resize((256, 256), Image.LANCZOS).save("app/icon.png", optimize=True)
sq.resize((96, 96), Image.LANCZOS).save("public/brand/mark-96.png", optimize=True)
apple = Image.new("RGBA", sq.size, (255, 255, 255, 255))
apple.alpha_composite(sq)
apple.convert("RGB").resize((180, 180), Image.LANCZOS).save("app/apple-icon.png", optimize=True)
sq.save("app/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
full = out.crop(out.getbbox())
full.thumbnail((800, 800), Image.LANCZOS)
full.save("public/brand/logo-full.png", optimize=True)

