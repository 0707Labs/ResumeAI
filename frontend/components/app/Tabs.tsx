"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useRef } from "react";

/** Tabs kept in the URL (?tab=), so a tab can be linked to and survives a reload.
 * Arrow keys, Home and End move between tabs (WAI-ARIA tabs pattern). */
export function useTab<T extends string>(tabs: readonly T[], fallback: T): [T, (t: T) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("tab");
  const current = (tabs as readonly string[]).includes(raw ?? "") ? (raw as T) : fallback;
  const select = (t: T) => {
    const next = new URLSearchParams(params.toString());
    next.set("tab", t);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };
  return [current, select];
}

export function TabList<T extends string>({ label, tabs, labels, current, onSelect, idPrefix }: {
  label: string; tabs: readonly T[]; labels: Record<T, string>; current: T; onSelect: (t: T) => void; idPrefix: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const move = (i: number) => {
    const n = (i + tabs.length) % tabs.length;
    onSelect(tabs[n]);
    refs.current[n]?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className="mb-6 flex gap-1 overflow-x-auto border-b border-border">
      {tabs.map((t, i) => (
        <button key={t} ref={(el) => { refs.current[i] = el; }} type="button" role="tab" id={`${idPrefix}-tab-${t}`}
          aria-selected={t === current} aria-controls={`${idPrefix}-panel-${t}`} tabIndex={t === current ? 0 : -1}
          onClick={() => onSelect(t)}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight") { e.preventDefault(); move(i + 1); }
            if (e.key === "ArrowLeft") { e.preventDefault(); move(i - 1); }
            if (e.key === "Home") { e.preventDefault(); move(0); }
            if (e.key === "End") { e.preventDefault(); move(tabs.length - 1); }
          }}
          className={`-mb-px min-h-10 whitespace-nowrap border-b-2 px-3 text-sm ${
            t === current ? "border-accent font-medium text-fg" : "border-transparent text-muted hover:text-fg"}`}>
          {labels[t]}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, idPrefix, children }: { id: string; idPrefix: string; children: React.ReactNode }) {
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-tab-${id}`} tabIndex={0}
      className="focus-visible:outline-none">
      {children}
    </div>
  );
}
