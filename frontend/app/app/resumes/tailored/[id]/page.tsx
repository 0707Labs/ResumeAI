"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AtsChange } from "@/components/app/AtsChange";
import { ErrorState, LoadingStatus, PageHeader, Skeleton } from "@/components/app/states";
import { Alert, Button, Card } from "@/components/ui";
import type { TailoringDetail } from "@/lib/schemas";
import { loadForTailoring } from "@/lib/tailorAgain";
import { userApi, userError } from "@/lib/user";

const day = (iso: string) => new Date(iso).toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" });

/** One past tailoring, read-only: the job, the scores, and the rewritten bullets with
 * the original each came from. "Tailor again" starts a fresh run from the same inputs. */
export default function TailoringPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [t, setT] = useState<TailoringDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    userApi.tailoring(id).then(setT).catch((e) => setError(userError(e)));
  }, [id]);
  useEffect(load, [load]);

  if (error) return <><PageHeader title="Tailoring" /><ErrorState message={error} onRetry={load} /></>;
  if (!t) return <><LoadingStatus /><Skeleton className="mb-6 h-8 w-64" /><Card className="space-y-3"><Skeleton className="h-16" /><Skeleton className="h-16" /></Card></>;

  const source = (ids: string[]) => ids.map((b) => t.resume?.sections.flatMap((s) => s.entries).flatMap((e) => e.bullets)
    .find((x) => x.id === b)?.text).filter(Boolean).join(" / ");
  return (
    <>
      <p className="mb-2 text-sm"><Link href="/app/resumes" className="text-muted hover:text-fg">← My resumes</Link></p>
      <PageHeader title={t.job_title ?? "Untitled role"}
        intro={<>{[t.company, day(t.created_at)].filter(Boolean).join(" · ")} · <AtsChange before={t.ats_before} after={t.ats_after} /></>}
        actions={t.content_available ? (
          <Button onClick={() => { if (loadForTailoring(t)) router.push("/app/tailor"); }}>Tailor again</Button>
        ) : undefined} />
      {!t.content_available ? (
        <Alert tone="info" title="We no longer keep this tailoring's text">
          Resumes and job descriptions are cleared after our retention period (see the Privacy Policy). The score
          and dates stay so your history makes sense.
        </Alert>
      ) : !t.tailored ? (
        <Alert tone="info" title="This one wasn't tailored">It was started but never got to the tailoring step.</Alert>
      ) : (
        <Card>
          <h2 className="font-medium text-fg">Rewritten bullets</h2>
          <p className="mt-1 text-sm text-muted">Each one with the original line it came from. Nothing here was added that your resume didn&apos;t say.</p>
          <ul className="mt-4 space-y-4">
            {t.tailored.bullets.map((b) => (
              <li key={b.id} className="rounded-xl border border-border p-4">
                <p className="text-fg">{b.text}</p>
                <p className="mt-2 text-sm text-muted"><span className="font-medium">Original:</span> {source(b.source_bullet_ids) || "from your answers"}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
