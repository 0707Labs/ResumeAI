"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AtsChange } from "@/components/app/AtsChange";
import { EmptyState, ErrorState, LoadingStatus, PageHeader, Skeleton } from "@/components/app/states";
import { CheckIcon } from "@/components/icons";
import { Button, Card } from "@/components/ui";
import type { ResumeSummary, TailoringSummary } from "@/lib/schemas";
import { loadForTailoring } from "@/lib/tailorAgain";
import { userApi, userError } from "@/lib/user";

const day = (iso: string) => new Date(iso).toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" });
const primary = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:bg-accent-hover";
const STATUS = { started: "Started", tailored: "Tailored", downloaded: "Downloaded" } as const;

export default function ResumesPage() {
  return (
    <>
      <PageHeader title="My resumes" intro="Your base resumes, and every resume you've tailored to a job."
        actions={<Link href="/app/tailor" className={primary}>Tailor a resume</Link>} />
      <div className="space-y-8">
        <BaseResumes />
        <Tailorings />
      </div>
    </>
  );
}

function BaseResumes() {
  const [list, setList] = useState<ResumeSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    userApi.resumes().then(setList).catch((e) => setError(userError(e)));
  }, []);
  useEffect(load, [load]);

  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try { await fn(); load(); } catch (e) { setError(userError(e)); } finally { setBusy(null); setConfirm(null); }
  }

  return (
    <section aria-labelledby="base-heading">
      <h2 id="base-heading" className="mb-3 text-lg font-semibold text-fg">Base resumes</h2>
      {error && <div className="mb-3"><ErrorState message={error} onRetry={load} /></div>}
      {!list ? (!error && <Card className="space-y-3"><LoadingStatus label="Loading your resumes" /><Skeleton className="h-12" /><Skeleton className="h-12" /></Card>)
        : list.length === 0 ? (
          <EmptyState title="No saved resumes"
            action={<Link href="/app/profile?tab=resume" className={primary}>Add your base resume</Link>}>
            Save your resume once, then pick it for every tailoring.
          </EmptyState>
        ) : (
          <Card as="div" className="p-0 sm:p-0">
            <ul className="divide-y divide-border">
              {list.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 font-medium text-fg">
                      <span className="truncate">{r.title}</span>
                      {r.is_default && <span className="flex items-center gap-1 rounded-md bg-accent-soft px-2 py-0.5 text-xs"><CheckIcon />Default</span>}
                    </p>
                    <p className="text-sm text-muted">Version {r.version} · updated {day(r.updated_at)}</p>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    <Link href={`/app/profile?tab=resume&resume=${r.id}`} aria-label={`Open ${r.title}`} className="inline-flex min-h-9 items-center rounded-lg px-3 text-sm font-medium text-accent hover:bg-surface-2">
                      Open
                    </Link>
                    <Button variant="ghost" className="min-h-9 px-3" busy={busy === `dup-${r.id}`} aria-label={`Duplicate ${r.title}`}
                      onClick={() => act(`dup-${r.id}`, () => userApi.duplicateResume(r.id))}>
                      Duplicate
                    </Button>
                    {confirm === r.id ? (
                      <span role="group" aria-label={`Confirm deleting ${r.title}`} className="flex items-center gap-1">
                        <Button variant="danger" className="min-h-9 px-3" busy={busy === `del-${r.id}`}
                          onClick={() => act(`del-${r.id}`, () => userApi.deleteResume(r.id))}>Delete it</Button>
                        <Button variant="ghost" className="min-h-9 px-3" onClick={() => setConfirm(null)} autoFocus>Cancel</Button>
                      </span>
                    ) : (
                      <Button variant="ghost" className="min-h-9 px-3 text-bad" aria-label={`Delete ${r.title}`} onClick={() => setConfirm(r.id)}>
                        Delete
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        )}
    </section>
  );
}

function Tailorings() {
  const router = useRouter();
  const [items, setItems] = useState<TailoringSummary[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  const load = useCallback((before?: string | null) => {
    setError(null);
    setBusy(before ? "more" : null);
    userApi.tailorings(before).then((p) => {
      setItems((cur) => (before && cur ? [...cur, ...p.items] : p.items));
      setNext(p.next_before);
    }).catch((e) => setError(userError(e))).finally(() => setBusy(null));
  }, []);
  useEffect(() => load(), [load]);

  async function again(id: string) {
    setBusy(`again-${id}`);
    setError(null);
    try {
      if (loadForTailoring(await userApi.tailoring(id))) router.push("/app/tailor");
      else setError("We no longer keep the text of that tailoring, so it can't be started again. Upload the resume and job description afresh.");
    } catch (e) {
      setError(userError(e));
    } finally {
      setBusy(null);
    }
  }
  async function remove(id: string) {
    setBusy(`del-${id}`);
    setError(null);
    try {
      await userApi.deleteTailoring(id);
      setItems((cur) => cur?.filter((t) => t.id !== id) ?? cur);
    } catch (e) {
      setError(userError(e));
    } finally {
      setBusy(null);
      setConfirm(null);
    }
  }

  return (
    <section aria-labelledby="tailored-heading">
      <h2 id="tailored-heading" className="mb-3 text-lg font-semibold text-fg">Tailored for jobs</h2>
      {error && <div className="mb-3"><ErrorState message={error} onRetry={items ? undefined : () => load()} /></div>}
      {!items ? (!error && <Card className="space-y-3"><LoadingStatus label="Loading your tailorings" /><Skeleton className="h-12" /><Skeleton className="h-12" /></Card>)
        : items.length === 0 ? (
          <EmptyState title="Nothing tailored yet" action={<Link href="/app/tailor" className={primary}>Tailor your first resume</Link>}>
            Each job you tailor for shows up here with its ATS score before and after.
          </EmptyState>
        ) : (
          <Card as="div" className="p-0 sm:p-0">
            <ul className="divide-y divide-border">
              {items.map((t) => {
                const name = t.job_title ?? "Untitled role";
                return (
                  <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium text-fg">{name}</p>
                      <p className="text-sm text-muted">{[t.company, day(t.created_at)].filter(Boolean).join(" · ")}</p>
                      <p className="mt-1 flex flex-wrap items-center gap-2">
                        <AtsChange before={t.ats_before} after={t.ats_after} />
                        <span className="rounded-md bg-surface-2 px-2 py-0.5 text-xs text-fg">{STATUS[t.status]}</span>
                        {!t.content_available && <span className="text-xs text-muted">Text cleared (retention)</span>}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      <Link href={`/app/resumes/tailored/${t.id}`} aria-label={`Open ${name}`} className="inline-flex min-h-9 items-center rounded-lg px-3 text-sm font-medium text-accent hover:bg-surface-2">
                        Open
                      </Link>
                      {t.content_available && (
                        <Button variant="ghost" className="min-h-9 px-3" busy={busy === `again-${t.id}`} aria-label={`Tailor again for ${name}`} onClick={() => again(t.id)}>
                          Tailor again
                        </Button>
                      )}
                      {confirm === t.id ? (
                        <span role="group" aria-label={`Confirm deleting ${name}`} className="flex items-center gap-1">
                          <Button variant="danger" className="min-h-9 px-3" busy={busy === `del-${t.id}`} onClick={() => remove(t.id)}>Delete it</Button>
                          <Button variant="ghost" className="min-h-9 px-3" onClick={() => setConfirm(null)} autoFocus>Cancel</Button>
                        </span>
                      ) : (
                        <Button variant="ghost" className="min-h-9 px-3 text-bad" aria-label={`Delete ${name}`} onClick={() => setConfirm(t.id)}>
                          Delete
                        </Button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </Card>
        )}
      {next && (
        <div className="mt-4 flex justify-center">
          <Button variant="secondary" busy={busy === "more"} onClick={() => load(next)}>Show older</Button>
        </div>
      )}
    </section>
  );
}
