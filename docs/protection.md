# Preview protection: what is and isn't protected

Resume Tailor lets people tailor and review for free, and charges for the clean file.
The preview before payment is built to make taking the file without paying less
convenient than paying. It is **deterrence, not absolute blocking**.

**Screenshots cannot be fully blocked on the web.** Anything a browser shows can be
photographed, screen-recorded or retyped. We don't try: no key listeners, no
visibility or focus tricks, no screenshot detection. They don't work reliably, and they
break accessibility and annoy honest users.

## What is protected

| Protection | Where | What it does |
|---|---|---|
| No clean file before payment | `POST /api/downloads/{fmt}` (backend) | The DOCX/PDF is rendered only after the entitlement check passes and the credit is charged in the same transaction. A 402 renders nothing. Enforced on the server, not in the UI. |
| Short-lived, per-user links | `GET /api/downloads/file/{token}` | The file comes only from an HMAC-signed link, valid for `[downloads].url_ttl_seconds` (120 s), for the signed-in user who paid. Someone else's session gets 404, an expired link 410. `Cache-Control: no-store`. |
| Image-only preview | `POST /api/export/preview`, `app/export/preview.py` | The preview is the same PDF the download would be, rasterized **on the server** at 60 dpi (about 510 × 660 px a page) and returned as PNGs. The response has no resume text, so there is nothing to select, copy or un-hide with developer tools. |
| Watermark baked in | same | A diagonal "PREVIEW - 0707Labs" is tiled across every page *in the pixels*, not as a CSS overlay. |
| Partial masking baked in | same | The contact line (email, phone, location, links) and the last section are Gaussian-blurred in the image on the server. It isn't text behind a CSS blur, so there's nothing to unblur. The name stays readable so people recognize their resume. |
| Light deterrents | `components/PreviewPages.tsx`, `globals.css` | On the preview only: no text selection (`select-none`), no context menu, no dragging the images, and hidden when printing (`@media print`). |
| Leak tracing | `routes.download_ref`, `export/render.py` | Each downloaded file carries `rt-dl-<download id>` in its metadata (DOCX core property *identifier*, PDF *Keywords*). We can map a leaked file back to the download and so the account. The id holds no personal data, and the Privacy Policy discloses it. |

## What is not protected

- **Screenshots and photos of the preview.** Someone can capture the low-resolution,
  watermarked, partly blurred images. Reconstructing a usable resume from them means
  retyping it, removing the watermark and filling in the blurred contact details and
  last section. That's more work than buying a credit.
- **The review screens.** To approve changes honestly, people have to read them, so the
  review page shows the tailored bullets as text. Someone could copy them by hand.
  That's deliberate: the honesty guarantee comes first. What's withheld is the
  assembled, formatted, clean file.
- **Metadata can be stripped.** The leak-tracing reference survives casual sharing
  (forwarding, uploading to a job site) but not "Save as" into a new document, export to
  another format, or a metadata scrubber. It traces careless leaks, not determined ones.
- **The paying user.** Once paid, the file is theirs to use; re-downloading the same
  resume is free for `[downloads].redownload_free_days` (7).
- **Browser extensions and developer tools** can switch off the CSS deterrents (selection,
  context menu, print). The images under them are still watermarked and masked.

## Changing it

- Resolution: `PREVIEW_DPI` in `backend/app/export/preview.py`. Higher is more readable
  and easier to reuse.
- Watermark text and strength: `WATERMARK` and the fill alpha in `_watermark()`.
- What's masked: `render_preview()` blurs the contact line and everything from the last
  section's heading on. `BLUR_RADIUS` sets the strength.
- Link lifetime and the re-download window: `[downloads]` in `backend/billing.toml`.

Tests: `backend/tests/test_export.py` (no text in the preview response, low resolution,
watermark present, contact and last section blurred, metadata reference) and
`backend/tests/test_analyses.py` (402 renders nothing, signed links, expiry, owner only).
