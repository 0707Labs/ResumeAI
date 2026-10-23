"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EmptyState, ErrorState, LoadingStatus, PageHeader, Skeleton } from "@/components/app/states";
import { Button, Card } from "@/components/ui";
import { openDownload } from "@/lib/download";
import type { DownloadItem } from "@/lib/schemas";
import { userApi, userError } from "@/lib/user";

const day = (iso: string) => new Date(iso).toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" });
const PAID = { credit: "Paid with a credit", pass: "Covered by your pass", pro: "Covered by Pro", window: "Free re-download" } as const;
const primary = "inline-flex min-h-10 items-center justify-center rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:bg-accent-hover";

/** Files you downloaded: get one again (free, while we keep it) or delete it now. */
export default function DownloadsPage() {
  const [items, setItems] = useState<DownloadItem[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  const load = useCallback((before?: string | null) => {
    setError(null);
    if (before) setBusy("more");
    userApi.downloads(before).then((p) => {
      setItems((cur) => (before && cur ? [...cur, ...p.items] : p.items));
      setNext(p.next_before);
    }).catch((e) => setError(userError(e))).finally(() => setBusy(null));
  }, []);
  useEffect(() => load(), [load]);

  async function again(d: DownloadItem) {
    setBusy(`get-${d.id}`);
    setError(null);
    try {
      openDownload((await userApi.redownload(d.id)).url);
    } catch (e) {
      load();  // the file may have just been cleared: show it as gone (load resets the error first)
      setError(userError(e));
    } finally {
      setBusy(null);
    }
  }
  async function remove(d: DownloadItem) {
    setBusy(`del-${d.id}`);
    setError(null);
    try {
      await userApi.deleteDownload(d.id);
      setItems((cur) => cur?.map((x) => (x.id === d.id ? { ...x, available: false, expires_at: new Date().toISOString() } : x)) ?? cur);
    } catch (e) {
      setError(userError(e));
    } finally {
      setBusy(null);
      setConfirm(null);
    }
  }

  return (
    <>
      <PageHeader title="Downloads" intro="Every clean file you downloaded. Download one again for free while we keep it; after that it's deleted for good." />
      {error && <div className="mb-4"><ErrorState message={error} onRetry={items ? undefined : () => load()} /></div>}
      {!items ? (!error && <Card className="space-y-3"><LoadingStatus label="Loading your downloads" />{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</Card>)
        : items.length === 0 ? (
          <EmptyState title="No downloads yet" action={<Link href="/app/tailor" className={primary}>Tailor a resume</Link>}>
            When you download a tailored resume, it shows up here so you can get it again.
          </EmptyState>
        ) : (
          <Card as="div" className="p-0 sm:p-0">
            <ul className="divide-y divide-border">
              {items.map((d) => {
                const job = [d.job_title ?? "Untitled role", d.company].filter(Boolean).join(" at ");
                return (
                  <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium text-fg">{d.file_name}</p>
                      <p className="text-sm text-muted">{job} · {d.format.toUpperCase()} · {day(d.created_at)}</p>
                      <p className="text-xs text-muted">
                        {PAID[d.paid_with]} · {d.available ? `Kept until ${day(d.expires_at)}` : `Deleted ${day(d.expires_at)}`}
                      </p>
                    </div>
                    {d.available ? (
                      <div className="flex flex-wrap gap-1">
                        <Button variant="secondary" className="min-h-9 px-3" busy={busy === `get-${d.id}`}
                          aria-label={`Download ${d.file_name} again`} onClick={() => again(d)}>Download again</Button>
                        {confirm === d.id ? (
                          <span role="group" aria-label={`Confirm deleting ${d.file_name}`} className="flex items-center gap-1">
                            <Button variant="danger" className="min-h-9 px-3" busy={busy === `del-${d.id}`} onClick={() => remove(d)}>Delete now</Button>
                            <Button variant="ghost" className="min-h-9 px-3" onClick={() => setConfirm(null)} autoFocus>Cancel</Button>
                          </span>
                        ) : (
                          <Button variant="ghost" className="min-h-9 px-3 text-bad" aria-label={`Delete ${d.file_name} now`}
                            onClick={() => setConfirm(d.id)}>Delete</Button>
                        )}
                      </div>
                    ) : (
                      <span className="text-sm text-muted">No longer kept</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </Card>
        )}
      {next && <div className="mt-4 flex justify-center"><Button variant="secondary" busy={busy === "more"} onClick={() => load(next)}>Show older</Button></div>}
    </>
  );
}
