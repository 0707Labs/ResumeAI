"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useId, useState } from "react";

import { Pill, when } from "@/components/admin/ui";
import { ErrorState, LoadingStatus, PageHeader, Skeleton } from "@/components/app/states";
import { Button, Card, Label, inputClass } from "@/components/ui";
import { adminApi, adminError } from "@/lib/adminApi";
import type { AdminTicketDetail } from "@/lib/schemas";

/** One ticket: the message, replies (emailed) and internal notes (staff only). */
export default function AdminTicketPage() {
  const { id } = useParams<{ id: string }>();
  const [t, setT] = useState<AdminTicketDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    adminApi.ticket(id).then(setT).catch((e) => setError(adminError(e)));
  }, [id]);
  useEffect(load, [load]);
  if (error && !t) return <><PageHeader title="Ticket" /><ErrorState message={error} onRetry={load} /></>;
  if (!t) return <><LoadingStatus /><Skeleton className="mb-4 h-8 w-80" /><Skeleton className="h-40" /></>;

  async function patch(body: { status?: string; assignee_id?: string; unassign?: boolean }) {
    setError(null);
    try { await adminApi.updateTicket(id, body); load(); } catch (e) { setError(adminError(e)); }
  }
  return (
    <>
      <p className="mb-2 text-sm"><Link href="/admin/support" className="text-muted hover:text-fg">← Support</Link></p>
      <PageHeader title={t.subject} intro={<>
        From {t.user_id ? <Link href={`/admin/users/${t.user_id}`} className="text-accent hover:underline">{t.email}</Link> : t.email} · {when(t.created_at)}
      </>} />
      {error && <p role="alert" className="mb-4 text-sm text-bad">{error}</p>}
      <div className="grid gap-6 lg:grid-cols-[1fr_16rem]">
        <div className="space-y-4">
          <Card><p className="whitespace-pre-wrap text-fg">{t.body}</p></Card>
          <ol className="space-y-3" aria-label="Conversation">
            {t.messages.map((m) => (
              <li key={m.id} className={`rounded-xl border p-4 ${m.kind === "internal_note" ? "border-warn/40 bg-warn-bg" : "border-border bg-surface"}`}>
                <p className="mb-1 text-xs text-muted">
                  {m.kind === "internal_note" ? "Internal note (not sent)" : `Reply, emailed ${when(m.emailed_at)}`} · {m.author_email ?? "staff"} · {when(m.created_at)}
                </p>
                <p className="whitespace-pre-wrap text-sm text-fg">{m.body}</p>
              </li>
            ))}
          </ol>
          <Compose kind="reply" onSend={(body) => adminApi.reply(id, body)} onSent={load} />
          <Compose kind="note" onSend={(body) => adminApi.note(id, body)} onSent={load} />
        </div>
        <Card className="h-fit space-y-4">
          <div>
            <Label htmlFor="ticket-status">Status</Label>
            <select id="ticket-status" className={inputClass} value={t.status} onChange={(e) => patch({ status: e.target.value })}>
              <option value="open">Open</option><option value="pending">Waiting on user</option><option value="closed">Closed</option>
            </select>
          </div>
          <div>
            <Label htmlFor="ticket-assignee">Assignee</Label>
            <select id="ticket-assignee" className={inputClass} value={t.assignee_id ?? ""}
              onChange={(e) => patch(e.target.value ? { assignee_id: e.target.value } : { unassign: true })}>
              <option value="">Unassigned</option>
              {t.staff.map((s) => <option key={s.id} value={s.id}>{s.email}</option>)}
            </select>
          </div>
          <p className="text-sm text-muted"><Pill>{t.category.replaceAll("_", " ")}</Pill></p>
          {t.analysis_id && <p className="text-xs text-muted">About tailoring <span className="font-mono">{t.analysis_id.slice(0, 8)}</span> (metadata in the user&apos;s page)</p>}
        </Card>
      </div>
    </>
  );
}

function Compose({ kind, onSend, onSent }: { kind: "reply" | "note"; onSend: (body: string) => Promise<unknown>; onSent: () => void }) {
  const id = useId();
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function send(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try { await onSend(body.trim()); setBody(""); onSent(); } catch (err) { setError(adminError(err)); } finally { setBusy(false); }
  }
  return (
    <Card as="form" onSubmit={send} className="space-y-3">
      <Label htmlFor={`${id}-b`} hint={kind === "reply" ? "(emailed to them)" : "(staff only, never sent)"}>
        {kind === "reply" ? "Reply" : "Internal note"}
      </Label>
      <textarea id={`${id}-b`} className={`${inputClass} min-h-24`} maxLength={5000} value={body} onChange={(e) => setBody(e.target.value)} />
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      <Button type="submit" variant={kind === "reply" ? "primary" : "secondary"} busy={busy} disabled={!body.trim()}>
        {kind === "reply" ? "Send reply" : "Add note"}
      </Button>
    </Card>
  );
}
