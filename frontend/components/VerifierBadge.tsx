import type { TailoredBullet } from "@/lib/schemas";
import { isBlocked, isFlagged } from "@/lib/review";

import { AlertIcon, ShieldIcon } from "./icons";

/** "Verified" only when the verifier raised nothing at all. Icon + word, not color alone. */
export function VerifierBadge({ bullet }: { bullet: TailoredBullet }) {
  if (!isFlagged(bullet)) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-ok/30 bg-ok-bg px-2 py-0.5 text-xs font-medium text-ok">
        <ShieldIcon className="h-3.5 w-3.5" /> Verified
      </span>
    );
  }
  const blocked = isBlocked(bullet);
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${
      blocked ? "border-bad/30 bg-bad-bg text-bad" : "border-warn/30 bg-warn-bg text-warn"
    }`}>
      <AlertIcon className="h-3.5 w-3.5" /> Needs your check
    </span>
  );
}
