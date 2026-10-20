"use client";

// Placeholder until Step 5.
import Link from "next/link";

import { useHydrated } from "@/components/AppShell";
import { Alert, Card } from "@/components/ui";
import { useSession } from "@/lib/store";

export default function MentorPage() {
  const hydrated = useHydrated();
  const ready = useSession((s) => !!s.analysis);
  if (!hydrated) return null;
  if (!ready) {
    return <Alert tone="info" title="Not yet">Start on the <Link href="/" className="font-medium text-accent underline">first step</Link>.</Alert>;
  }
  return (
    <Card>
      <h1 className="text-xl font-semibold">Mentor</h1>
      <p className="mt-2 text-muted">This screen comes in Step 5.</p>
    </Card>
  );
}
