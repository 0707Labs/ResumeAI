# Assets and licences

Every image, icon, font and visual asset the frontend ships, where it came from, and the
terms we use it under. Add a row before adding an asset; if the licence is unclear, don't
ship it.

Last reviewed: 2026-10-23 (landing redesign, branch `redesign/tokens`).

## Shipped assets

| Asset | Files | Source | Licence / basis | Notes |
|---|---|---|---|---|
| Resume Tailor logo (document mark + wordmark) | `frontend/brand/logo-source.webp` → `app/favicon.ico`, `app/icon.png`, `app/apple-icon.png`, `public/brand/mark-96.png`, `public/brand/logo-full.png` | Supplied by 0707Labs (commit 33aaee1); derived files made by `frontend/brand/make_brand.py` | Owned by 0707Labs / MealOBox Foodtech Pvt Ltd | **To confirm:** how the source image was made (designer, tool, AI generator) and that its terms grant us commercial use and trademark rights. Record the answer here. |
| UI icons | `frontend/components/icons.tsx` (inline SVG) | Several paths are identical to [Lucide](https://lucide.dev) icons (check, upload, alert-triangle, info, file, circle-x, log-out and others in the same 24px/2px-stroke style); the rest were drawn to match | Lucide: ISC licence (notice below). Lucide includes work from Feather (MIT). | Inline SVG, no icon font, no network request. Keep the notice below while any Lucide-derived path ships. |
| Google "G" mark | `frontend/components/auth/ProviderButtons.tsx` (`GoogleMark`) | Google Identity sign-in branding | Trademark of Google LLC, used unmodified on the "Continue with Google" button as the [sign-in branding guidelines](https://developers.google.com/identity/branding-guidelines) require | Not a licence to use elsewhere. Only on sign-in buttons. |
| GitHub Invertocat mark | `frontend/components/auth/ProviderButtons.tsx` (`GitHubMark`) | GitHub logos page (same path as the Octicons `mark-github` icon) | Trademark of GitHub, Inc., used unmodified in one solid colour per GitHub's [logo guidelines](https://github.com/logos) | Only on the "Continue with GitHub" button. |
| Hero and sample illustrations | `frontend/components/site/BeforeAfter.tsx`, `app/page.tsx` | Our own HTML/CSS, made-up resume text | Ours | No stock photos, no images of people. |
| Fonts | none | System UI stack (`ui-sans-serif, system-ui, …`), `ui-monospace` for source ids | Fonts installed on the visitor's device | No web fonts are downloaded. The Google button names Roboto but only uses it when it is already installed. |

## Images not served through `next/image`

`next/image` is used for every static image (`BrandLogo`). Two `<img>` tags are left as they
are on purpose; neither appears on the landing page:

- `components/PreviewPages.tsx`: the watermarked resume preview, delivered as `data:` URLs
  by `/api/export/preview` with known width and height. There is nothing for the image
  optimiser to fetch or resize.
- `components/app/Avatar.tsx`: the signed-in user's avatar. Remote and per-user, with a
  fixed size class, so it can't shift layout.

## References used for inspiration only

These were looked at for layout ideas. Nothing was copied, and no files from them ship:
Supahero, CTA.gallery, Navbar Gallery, Footer, Refero.

Considered, not used: **3dicons** (3D icon packs) and **Scrolltide** (scroll animation
components). The scroll reveal is our own CSS (`.reveal` in `app/globals.css`). If either is
adopted later, check its licence first and add a row above.

## Licence notices

### Lucide (ISC)

Source: https://github.com/lucide-icons/lucide/blob/main/LICENSE. Check that this text still
matches it when updating icons.

```
ISC License

Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT).
All other copyright (c) for Lucide are held by Lucide Contributors 2022.

Permission to use, copy, modify, and/or distribute this software for any purpose with or
without fee is hereby granted, provided that the above copyright notice and this permission
notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS
SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE
AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT,
NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
```
