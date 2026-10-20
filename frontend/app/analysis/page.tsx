"use client";

// Placeholder until Step 2: shows that the analysis arrived so Step 1 can be checked
// end to end. Step 2 replaces this with the full gap and question screen.
import Link from "next/link";

import { useHydrated } from "@/components/AppShell";
import { Alert, Card } from "@/components/ui";
import { useSession } from "@/lib/store";

export default function AnalysisPage() {
  const hydrated = useHydrated();
  const { analysis, jd } = useSession();
  if (!hydrated) return null;
  if (!analysis) {
    return (
      <Alert tone="info" title="Nothing to show yet">
        Start on the <Link href="/" className="font-medium text-accent underline">first step</Link> with your resume
        and a job description.
      </Alert>
    );
  }
  return (
    <Card>
      <h1 className="text-xl font-semibold">Gap analysis{jd?.title ? ` for ${jd.title}` : ""}</h1>
      <p className="mt-2 text-muted">
        {analysis.counts.evidenced} evidenced · {analysis.counts.implied} implied · {analysis.counts.missing} missing.
        The full gap and question screen comes in Step 2.
      </p>
    </Card>
  );
}
