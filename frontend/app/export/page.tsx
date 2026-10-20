"use client";

// Placeholder until Step 6.
import Link from "next/link";

import { useHydrated } from "@/components/AppShell";
import { Alert, Card } from "@/components/ui";
import { useSession } from "@/lib/store";

export default function ExportPage() {
  const hydrated = useHydrated();
  const ready = useSession((s) => !!s.tailored);
  if (!hydrated) return null;
  if (!ready) {
    return <Alert tone="info" title="Not yet">Start on the <Link href="/" className="font-medium text-accent underline">first step</Link>.</Alert>;
  }
  return (
    <Card>
      <h1 className="text-xl font-semibold">Export</h1>
      <p className="mt-2 text-muted">This screen comes in Step 6.</p>
    </Card>
  );
}
