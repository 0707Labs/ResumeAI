"use client";

import { useEffect, useId, useRef, useState } from "react";

import { EmptyState, Skeleton } from "@/components/app/states";
import { Button, Label, inputClass } from "@/components/ui";

export const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" }) : "—";
export const day = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" }) : "—";

export interface Column<T> {
  key: string;
  label: string;
  sortable?: boolean;
  className?: string;
  render: (row: T) => React.ReactNode;
}

/** A server-paged table: the page, sort and filters live with the caller (and the URL). */
export function DataTable<T extends { id: string }>({ label, columns, rows, sort, direction, onSort, empty }: {
  label: string; columns: Column<T>[]; rows: T[] | null; sort?: string; direction?: "asc" | "desc";
  onSort?: (key: string) => void; empty: string;
}) {
  if (rows === null) {
    return <div className="space-y-2"><p role="status" className="sr-only">Loading</p>{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10" />)}</div>;
  }
  if (rows.length === 0) return <EmptyState title={empty} />;
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-[40rem] text-left text-sm" aria-label={label}>
        <thead className="bg-surface-2 text-xs text-muted">
          <tr>
            {columns.map((c) => {
              const active = sort === c.key;
              return (
                <th key={c.key} scope="col" className={`px-3 py-2 font-medium ${c.className ?? ""}`}
                  aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : undefined}>
                  {c.sortable && onSort ? (
                    <button type="button" onClick={() => onSort(c.key)} className="inline-flex items-center gap-1 hover:text-fg">
                      {c.label}<span aria-hidden="true">{active ? (direction === "asc" ? "▲" : "▼") : "↕"}</span>
                    </button>
                  ) : c.label}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-border bg-surface">
          {rows.map((r) => (
            <tr key={r.id}>
              {columns.map((c) => <td key={c.key} className={`px-3 py-2 align-top text-fg ${c.className ?? ""}`}>{c.render(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const last = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav aria-label="Pages" className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-muted">
      <span>{total === 0 ? "No results" : `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total}`}</span>
      <span className="flex gap-2">
        <Button variant="secondary" className="min-h-9 px-3" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <Button variant="secondary" className="min-h-9 px-3" disabled={page >= last} onClick={() => onPage(page + 1)}>Next</Button>
      </span>
    </nav>
  );
}

export function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "ok" | "warn" | "bad" }) {
  const cls = { neutral: "bg-surface-2 text-fg", ok: "bg-ok-bg text-ok", warn: "bg-warn-bg text-warn", bad: "bg-bad-bg text-bad" }[tone];
  return <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${cls}`}>{children}</span>;
}

/**
 * Confirm an admin change. A reason (3+ characters) is required: it goes into the audit
 * log. `extra` renders more fields above it; `onConfirm` gets the reason.
 */
export function ReasonDialog({ title, description, confirm, danger, extra, onConfirm, onClose, valid = true }: {
  title: string; description?: React.ReactNode; confirm: string; danger?: boolean; extra?: React.ReactNode;
  onConfirm: (reason: string) => Promise<void>; onClose: () => void; valid?: boolean;
}) {
  const id = useId();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    document.addEventListener("keydown", onKey);
    box.current?.querySelector<HTMLElement>("input, textarea, select")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center">
      <div ref={box} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`}
        className="w-full max-w-md rounded-2xl border border-border bg-surface p-5 shadow-xl">
        <form onSubmit={submit} className="space-y-4">
          <h2 id={`${id}-title`} className="text-lg font-semibold text-fg">{title}</h2>
          {description && <div className="text-sm text-muted">{description}</div>}
          {extra}
          <div>
            <Label htmlFor={`${id}-reason`} hint="(kept in the audit log)">Reason</Label>
            <textarea id={`${id}-reason`} className={`${inputClass} min-h-20`} value={reason} maxLength={500} required
              onChange={(e) => setReason(e.target.value)} />
          </div>
          {error && <p role="alert" className="text-sm text-bad">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
            <Button type="submit" variant={danger ? "danger" : "primary"} busy={busy} disabled={reason.trim().length < 3 || !valid}>
              {confirm}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
