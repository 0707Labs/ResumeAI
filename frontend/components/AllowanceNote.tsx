"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Allowance } from "@/lib/schemas";

const month = (iso: string) =>
  new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "long", timeZone: "UTC" });

/** What the next Analyze uses: a free tailoring, a pass, Pro or the credit balance.
 * Tailoring never spends credits; only the clean download does. `refresh` re-reads it. */
export function AllowanceNote({ refresh = 0 }: { refresh?: number }) {
  const [allowance, setAllowance] = useState<Allowance | null>(null);
  useEffect(() => {
    let live = true;
    api.allowance().then((a) => { if (live) setAllowance(a); }).catch(() => {});
    return () => { live = false; };
  }, [refresh]);
  if (!allowance) return null;

  const left = allowance.free_allowance - allowance.free_used;
  const resets = month(allowance.resets_at);
  let text: React.ReactNode;
  switch (allowance.next_uses) {
    case "free":
      text = `${left} of ${allowance.free_allowance} free tailorings left this month (resets ${resets}).`;
      break;
    case "pass":
      text = "This tailoring is covered by your Job Hunt Pass.";
      break;
    case "pro":
      text = "This tailoring is covered by Pro.";
      break;
    case "credit":
      text = `You've used this month's free tailorings. You can keep tailoring with your ${allowance.credits_balance} ` +
        `credit${allowance.credits_balance === 1 ? "" : "s"}; nothing is spent until you download.`;
      break;
    default:
      text = (
        <>
          You&apos;ve used this month&apos;s {allowance.free_allowance} free tailorings (they reset {resets}).{" "}
          <Link href="/pricing" className="font-medium text-accent underline">Get credits or a pass</Link> to keep going.
        </>
      );
  }
  return <p data-testid="allowance" className="text-sm text-muted">{text}</p>;
}
