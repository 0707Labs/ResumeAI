/** "62 → 78" with the change; the word says the direction, not only the colour. */
export function AtsChange({ before, after }: { before: number | null; after: number | null }) {
  if (before === null) return <span className="text-xs text-muted">No score yet</span>;
  if (after === null) return <span className="text-sm text-fg">ATS {Math.round(before)}</span>;
  const [from, to] = [Math.round(before), Math.round(after)];
  const delta = to - from;  // from the shown numbers, so the sum adds up on screen
  return (
    <span className="text-sm text-fg" title="ATS score before and after tailoring">
      ATS {from} → {to}{" "}
      <span className={delta > 0 ? "text-ok" : "text-muted"}>({delta > 0 ? `up ${delta}` : delta < 0 ? `down ${-delta}` : "no change"})</span>
    </span>
  );
}
