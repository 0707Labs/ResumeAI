"use client";

// Placeholder until Step 4 (score dashboard).
import Link from "next/link";

import { useHydrated } from "@/components/AppShell";
import { Alert, Card } from "@/components/ui";
import { useSession } from "@/lib/store";

export default function ScorePage() {
  const hydrated = useHydrated();
  const score = useSession((s) => s.score);
  if (!hydrated) return null;
  if (!score) {
    return <Alert tone="info" title="No score yet">Review your changes on the <Link href="/review" className="font-medium text-accent underline">review page</Link> first.</Alert>;
  }
  return (
    <Card>
      <h1 className="text-xl font-semibold">ATS score</h1>
      <p className="mt-2 text-muted">
        {score.before.total.toFixed(1)} → {(score.after?.total ?? score.before.total).toFixed(1)}. The full dashboard comes in Step 4.
      </p>
    </Card>
  );
}
