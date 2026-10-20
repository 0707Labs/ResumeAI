import type { GapStatus } from "@/lib/schemas";

import { AlertIcon, CheckIcon, ErrorIcon } from "./icons";

export const STATUS: Record<GapStatus, { word: string; cls: string; Icon: typeof CheckIcon }> = {
  evidenced: { word: "Evidenced", cls: "bg-ok-bg text-ok border-ok/30", Icon: CheckIcon },
  implied: { word: "Implied", cls: "bg-warn-bg text-warn border-warn/30", Icon: AlertIcon },
  missing: { word: "Missing", cls: "bg-bad-bg text-bad border-bad/30", Icon: ErrorIcon },
};

/** Icon + word + color, so the status reads without relying on color. */
export function StatusBadge({ status }: { status: GapStatus }) {
  const { word, cls, Icon } = STATUS[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${cls}`}>
      <Icon className="h-3.5 w-3.5" />
      {word}
    </span>
  );
}

export function PriorityBadge({ priority }: { priority: "required" | "preferred" }) {
  return (
    <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-xs text-muted">
      {priority === "required" ? "Required" : "Nice to have"}
    </span>
  );
}
