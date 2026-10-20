"use client";

// Placeholder until Step 3 (diff review). Confirms the answers arrived.
import Link from "next/link";

import { useHydrated } from "@/components/AppShell";
import { Alert, Card } from "@/components/ui";
import { useSession } from "@/lib/store";

export default function ReviewPage() {
  const hydrated = useHydrated();
  const analysis = useSession((s) => s.analysis);
  if (!hydrated) return null;
  if (!analysis) {
    return (
      <Alert tone="info" title="Nothing to review yet">
        Start on the <Link href="/" className="font-medium text-accent underline">first step</Link>.
      </Alert>
    );
  }
  const answered = analysis.items.filter((i) => i.question?.answer_kind === "confirmed").length;
  return (
    <Card>
      <h1 className="text-xl font-semibold">Review</h1>
      <p className="mt-2 text-muted">
        Your answers are saved ({answered} confirmed). The side-by-side review screen comes in Step 3.
      </p>
    </Card>
  );
}
