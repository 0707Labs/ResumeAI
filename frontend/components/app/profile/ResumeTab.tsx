"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useId, useState } from "react";

import { ListInput } from "@/components/app/PreferencesForm";
import { EmptyState, ErrorState, LoadingStatus, Skeleton } from "@/components/app/states";
import { CheckIcon, TrashIcon } from "@/components/icons";
import { UploadDropzone } from "@/components/UploadDropzone";
import { Alert, Button, Card, Label, inlineInputClass, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { blankEntry, cleanForSave, nextBulletId, sameResume } from "@/lib/resumeEdit";
import type { Resume, ResumeDetail, ResumeSummary, VersionSummary } from "@/lib/schemas";
import { userApi, userError } from "@/lib/user";

const day = (iso: string) => new Date(iso).toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" });
const SOURCE = { upload: "Uploaded", paste: "Pasted", edit: "Edited" } as const;

/** Profile > Resume details: saved base resumes, edited as structured sections. Every
 * save is a new version; older versions stay readable and can be restored. */
export function ResumeTab() {
  const params = useSearchParams();
  const router = useRouter();
  const [list, setList] = useState<ResumeSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const wanted = params.get("resume");

  const load = useCallback(() => {
    setLoadError(null);
    return userApi.resumes().then((l) => { setList(l); return l; }).catch((e) => { setLoadError(userError(e)); return null; });
  }, []);
  useEffect(() => { void load(); }, [load]);

  const select = (id: string) => {
    const next = new URLSearchParams(params.toString());
    next.set("tab", "resume");
    next.set("resume", id);
    router.replace(`/app/profile?${next.toString()}`, { scroll: false });
  };

  if (loadError) return <ErrorState message={loadError} onRetry={() => void load()} />;
  if (!list) return <Card className="space-y-3"><LoadingStatus label="Loading your resumes" /><Skeleton className="h-10" /><Skeleton className="h-40" /></Card>;
  if (list.length === 0) return <FirstResume onSaved={async (id) => { await load(); select(id); }} />;

  const current = list.find((r) => r.id === wanted) ?? list.find((r) => r.is_default) ?? list[0];
  return (
    <div className="space-y-4">
      {list.length > 1 && (
        <div className="flex flex-wrap items-center gap-2">
          <Label htmlFor="resume-picker">Resume</Label>
          <select id="resume-picker" className={inlineInputClass} value={current.id} onChange={(e) => select(e.target.value)}>
            {list.map((r) => <option key={r.id} value={r.id}>{r.title}{r.is_default ? " (default)" : ""}</option>)}
          </select>
        </div>
      )}
      <ResumeEditor key={current.id} summary={current} onChanged={load} onSelect={select}
        onDeleted={async () => { const l = await load(); if (l?.[0]) select(l[0].id); }} />
    </div>
  );
}

function FirstResume({ onSaved }: { onSaved: (id: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Card className="space-y-4">
      <EmptyState title="No saved resume yet">
        Upload your base resume once and pick it for every tailoring. You can edit it here, section by section.
      </EmptyState>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      <UploadDropzone busy={busy} onReject={setError} onFile={async (file) => {
        setBusy(true);
        setError(null);
        try {
          const resume = await api.parseResumeFile(file);
          const saved = await userApi.saveResume({ resume, source: "upload", file_name: file.name });
          onSaved(saved.id);
        } catch (e) {
          setError(userError(e));
        } finally {
          setBusy(false);
        }
      }} />
    </Card>
  );
}

function ResumeEditor({ summary, onChanged, onDeleted, onSelect }: {
  summary: ResumeSummary; onChanged: () => void; onDeleted: () => void; onSelect: (id: string) => void;
}) {
  const id = useId();
  const [detail, setDetail] = useState<ResumeDetail | null>(null);
  const [draft, setDraft] = useState<Resume | null>(null);
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [title, setTitle] = useState(summary.title);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [newBullet, setNewBullet] = useState<string | null>(null);  // focus it once it mounts

  const open = useCallback(async (version?: number) => {
    setError(null);
    try {
      const [d, v] = await Promise.all([userApi.resume(summary.id, version), userApi.versions(summary.id)]);
      setDetail(d);
      setDraft(d.resume);
      setVersions(v);
    } catch (e) {
      setError(userError(e));
    }
  }, [summary.id]);
  useEffect(() => { void open(); }, [open]);

  async function act(label: string, fn: () => Promise<unknown>, done?: string) {
    setBusy(label);
    setError(null);
    setSaved(null);
    try { await fn(); if (done) setSaved(done); } catch (e) { setError(userError(e)); } finally { setBusy(null); }
  }

  if (!detail || !draft) {
    return error ? <ErrorState message={error} onRetry={() => void open()} /> : (
      <Card className="space-y-3"><LoadingStatus label="Loading the resume" /><Skeleton className="h-8 w-56" /><Skeleton className="h-32" /></Card>
    );
  }
  const old = detail.shown_version !== detail.version;
  const dirty = !sameResume(draft, detail.resume);
  const update = (fn: (r: Resume) => Resume) => { setDraft((r) => (r ? fn(structuredClone(r)) : r)); setSaved(null); };
  const save = (resume: Resume, done: string) => act("save", async () => {
    const next = await userApi.addVersion(summary.id, { resume: cleanForSave(resume), source: "edit" });
    setDetail(next);
    setDraft(next.resume);
    setVersions(await userApi.versions(summary.id));
    onChanged();
  }, done);

  return (
    <div className="space-y-4">
      <Card className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1">
            <Label htmlFor={`${id}-title`}>Title</Label>
            <input id={`${id}-title`} className={inputClass} value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <Button variant="secondary" disabled={!title.trim() || title.trim() === summary.title} busy={busy === "rename"}
            onClick={() => act("rename", async () => { await userApi.updateResume(summary.id, { title: title.trim() }); onChanged(); }, "Renamed")}>
            Rename
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {summary.is_default ? (
            <span className="flex items-center gap-1 rounded-md bg-accent-soft px-2 py-1 text-xs font-medium text-fg"><CheckIcon />Default resume</span>
          ) : (
            <Button variant="secondary" className="min-h-9 px-3" busy={busy === "default"}
              onClick={() => act("default", async () => { await userApi.updateResume(summary.id, { is_default: true }); onChanged(); }, "Now your default")}>
              Make default
            </Button>
          )}
          <Button variant="secondary" className="min-h-9 px-3" busy={busy === "duplicate"}
            onClick={() => act("duplicate", async () => { const c = await userApi.duplicateResume(summary.id); onChanged(); onSelect(c.id); })}>
            Duplicate
          </Button>
          <Button variant="secondary" className="min-h-9 px-3" onClick={() => setReplacing((r) => !r)} aria-expanded={replacing}>
            Upload a new version
          </Button>
          {confirmDelete ? (
            <span role="group" aria-label="Confirm deleting this resume" className="flex items-center gap-2">
              <span className="text-sm">Delete it and all its versions?</span>
              <Button variant="danger" className="min-h-9 px-3" busy={busy === "delete"}
                onClick={() => act("delete", async () => { await userApi.deleteResume(summary.id); onDeleted(); })}>Delete</Button>
              <Button variant="ghost" className="min-h-9 px-3" onClick={() => setConfirmDelete(false)} autoFocus>Cancel</Button>
            </span>
          ) : (
            <Button variant="ghost" className="min-h-9 px-3 text-bad" onClick={() => setConfirmDelete(true)}><TrashIcon />Delete</Button>
          )}
        </div>
        {replacing && (
          <UploadDropzone busy={busy === "upload"} onReject={setError} onFile={(file) => act("upload", async () => {
            const resume = await api.parseResumeFile(file);
            const next = await userApi.addVersion(summary.id, { resume, source: "upload", file_name: file.name });
            setDetail(next); setDraft(next.resume); setReplacing(false);
            setVersions(await userApi.versions(summary.id));
            onChanged();
          }, "New version saved")} />
        )}
        {error && <p role="alert" className="text-sm text-bad">{error}</p>}
        {saved && <p role="status" className="flex items-center gap-1 text-sm text-ok"><CheckIcon />{saved}</p>}
      </Card>

      {old && (
        <Alert tone="info" title={`Viewing version ${detail.shown_version} of ${detail.version}`}>
          <span className="flex flex-wrap items-center gap-3">
            Changes here would be saved as a new version.
            <Button variant="secondary" className="min-h-9 px-3" busy={busy === "save"}
              onClick={() => save(draft, `Version ${detail.shown_version} restored`)}>Restore this version</Button>
            <Button variant="ghost" className="min-h-9 px-3" onClick={() => void open()}>Back to the latest</Button>
          </span>
        </Alert>
      )}

      <Card className="space-y-6">
        <div>
          <Label htmlFor={`${id}-summary`}>Summary</Label>
          <textarea id={`${id}-summary`} className={`${inputClass} min-h-24`} value={draft.summary ?? ""}
            onChange={(e) => update((r) => ({ ...r, summary: e.target.value }))} />
        </div>
        <ListInput id={`${id}-skills`} label="Skills" hint="(up to 60)" placeholder="e.g. SQL" max={60}
          values={draft.skills} onChange={(skills) => update((r) => ({ ...r, skills }))} />
        {draft.sections.map((section, si) => (
          <fieldset key={`${section.kind}-${si}`} className="space-y-4 border-t border-border pt-4">
            <legend className="sr-only">{section.heading}</legend>
            <input aria-label="Section heading" className={`${inputClass} mt-0 font-medium`} value={section.heading}
              onChange={(e) => update((r) => { r.sections[si].heading = e.target.value; return r; })} />
            {section.entries.map((entry, ei) => (
              <div key={entry.id} className="space-y-3 rounded-xl border border-border p-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  {(["title", "organization", "location"] as const).map((f) => (
                    <input key={f} aria-label={`${f[0].toUpperCase()}${f.slice(1)}`} placeholder={f === "title" ? "Title" : f === "organization" ? "Organization" : "Location"}
                      className={`${inputClass} mt-0`} value={entry[f] ?? ""}
                      onChange={(e) => update((r) => { r.sections[si].entries[ei][f] = e.target.value; return r; })} />
                  ))}
                  <div className="flex gap-2">
                    {(["start_date", "end_date"] as const).map((f) => (
                      <input key={f} aria-label={f === "start_date" ? "Start" : "End"} placeholder={f === "start_date" ? "Start" : "End"}
                        className={`${inputClass} mt-0`} value={entry[f] ?? ""}
                        onChange={(e) => update((r) => { r.sections[si].entries[ei][f] = e.target.value; return r; })} />
                    ))}
                  </div>
                </div>
                <ul className="space-y-2" aria-label={`Bullets for ${entry.title || "this entry"}`}>
                  {entry.bullets.map((b, bi) => (
                    <li key={b.id} className="flex gap-2">
                      <textarea aria-label={`Bullet ${bi + 1}, ${entry.title || "untitled entry"}`} className={`${inputClass} mt-0 min-h-16`} value={b.text}
                        autoFocus={b.id === newBullet}
                        onChange={(e) => update((r) => { r.sections[si].entries[ei].bullets[bi].text = e.target.value; return r; })} />
                      <button type="button" aria-label={`Remove bullet ${bi + 1}, ${entry.title || "untitled entry"}`}
                        onClick={() => update((r) => { r.sections[si].entries[ei].bullets.splice(bi, 1); return r; })}
                        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-bad"><TrashIcon /></button>
                    </li>
                  ))}
                </ul>
                <div className="flex flex-wrap gap-2">
                  <Button variant="ghost" className="min-h-9 px-3" aria-label={`Add a bullet to ${entry.title || "untitled entry"}`}
                    onClick={() => {
                      const bid = nextBulletId(entry);
                      setNewBullet(bid);
                      update((r) => { r.sections[si].entries[ei].bullets.push({ id: bid, text: "" }); return r; });
                    }}>
                    Add a bullet
                  </Button>
                  <Button variant="ghost" className="min-h-9 px-3 text-bad" aria-label={`Remove ${entry.title || "untitled entry"}`}
                    onClick={() => update((r) => { r.sections[si].entries.splice(ei, 1); return r; })}>Remove this entry</Button>
                </div>
              </div>
            ))}
            <Button variant="secondary" className="min-h-9 px-3"
              onClick={() => update((r) => { r.sections[si].entries.push(blankEntry(r, section.kind)); return r; })}>
              Add to {section.heading || "this section"}
            </Button>
          </fieldset>
        ))}
        <div className="sticky bottom-20 z-10 flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface p-3 shadow-sm md:bottom-4">
          <Button busy={busy === "save"} disabled={!dirty} onClick={() => save(draft, "Saved as a new version")}>
            Save as version {detail.version + 1}
          </Button>
          {dirty && <Button variant="ghost" onClick={() => { setDraft(detail.resume); setSaved(null); }}>Discard changes</Button>}
          <span className="text-sm text-muted">{dirty ? "Unsaved changes" : "No changes"}</span>
        </div>
      </Card>

      <Card>
        <h2 className="font-medium text-fg">Versions</h2>
        <ul className="mt-3 divide-y divide-border">
          {versions.map((v) => (
            <li key={v.version} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span className="text-sm text-fg">
                Version {v.version} · {SOURCE[v.source]}{v.file_name ? ` (${v.file_name})` : ""} · <span className="text-muted">{day(v.created_at)}</span>
                {v.version === detail.version && <span className="ml-2 text-xs text-muted">latest</span>}
              </span>
              {v.version !== detail.shown_version && (
                <Button variant="ghost" className="min-h-9 px-3" onClick={() => void open(v.version === detail.version ? undefined : v.version)}>
                  View
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
