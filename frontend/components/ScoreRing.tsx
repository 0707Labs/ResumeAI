"use client";

import { useEffect, useState } from "react";

const R = 52;
const CIRC = 2 * Math.PI * R;

export const clampScore = (v: number) => Math.max(0, Math.min(100, v));

/** Score out of 100 as a progress ring. Animates from 0 on mount (unless the user
 * prefers reduced motion, handled globally in CSS). The number is real text. */
export function ScoreRing({ value, label, tone = "accent", size = 148 }: {
  value: number;
  label: string;
  tone?: "accent" | "muted";
  size?: number;
}) {
  const v = clampScore(value);
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(v));
    return () => cancelAnimationFrame(id);
  }, [v]);

  return (
    <figure className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: size, height: size }}>
        <svg viewBox="0 0 120 120" width={size} height={size} role="img" aria-label={`${label}: ${v.toFixed(1)} out of 100`}>
          <circle cx="60" cy="60" r={R} fill="none" stroke="var(--surface-2)" strokeWidth="10" />
          <circle
            cx="60" cy="60" r={R} fill="none"
            stroke={tone === "accent" ? "var(--accent)" : "var(--border-strong)"}
            strokeWidth="10" strokeLinecap="round"
            strokeDasharray={CIRC}
            strokeDashoffset={CIRC * (1 - shown / 100)}
            transform="rotate(-90 60 60)"
            style={{ transition: "stroke-dashoffset 900ms cubic-bezier(.2,.8,.2,1)" }}
            data-testid="ring-arc"
          />
        </svg>
        <div aria-hidden className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-semibold tabular-nums">{v.toFixed(1)}</span>
          <span className="text-xs text-muted">of 100</span>
        </div>
      </div>
      <figcaption className="text-sm font-medium text-muted">{label}</figcaption>
    </figure>
  );
}
