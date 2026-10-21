"use client";

import type { ExportPreview } from "@/lib/schemas";

/**
 * The pre-payment preview: page images rendered on the server with the watermark and
 * masking baked in. Light deterrents only (no selecting, no context menu, no dragging,
 * hidden when printing); screenshots can't be blocked on the web, see docs/protection.md.
 */
export function PreviewPages({ preview }: { preview: ExportPreview }) {
  return (
    <div data-testid="preview-pages" className="preview-protected space-y-4 select-none"
      onContextMenu={(e) => e.preventDefault()} onDragStart={(e) => e.preventDefault()}>
      {preview.pages.map((page, i) => (
        // eslint-disable-next-line @next/next/no-img-element -- a server-rendered data URL, not an asset
        <img key={i} src={page.image} width={page.width} height={page.height} draggable={false}
          alt={`Preview of page ${i + 1} of ${preview.pages.length}, watermarked`}
          className="mx-auto block h-auto w-full max-w-[42rem] rounded-md border border-border bg-white shadow-sm" />
      ))}
    </div>
  );
}
