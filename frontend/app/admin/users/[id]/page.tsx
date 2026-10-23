"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useId, useState } from "react";

import { Pill, ReasonDialog, day, when } from "@/components/admin/ui";
import { ErrorState, LoadingStatus, PageHeader, Skeleton } from "@/components/app/states";
import { Button, Card, Label, inputClass } from "@/components/ui";
import { adminApi, adminError, attempt } from "@/lib/adminApi";
import type { AdminUserDetail } from "@/lib/schemas";

type Rec = Record<string, unknown>;
const str = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));
type Action = "suspend" | "unsuspend" | "signout" | "credits" | "pass" | "delete";

/** One user: everything about the account except what they wrote (no resume or JD text). */
export default function AdminUserPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<AdminUserDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    adminApi.user(id).then(setData).catch((e) => setError(adminError(e)));
  }, [id]);
  useEffect(load, [load]);

  if (error) return <><PageHeader title="User" /><ErrorState message={error} onRetry={load} /></>;
  if (!data) return <><LoadingStatus /><Skeleton className="mb-6 h-8 w-72" /><div className="space-y-4"><Skeleton className="h-32" /><Skeleton className="h-48" /></div></>;
  const u = data.user;
  const done = (msg: string) => { setNotice(msg); load(); };

  return (
    <>
      <p className="mb-2 text-sm"><Link href="/admin/users" className="text-muted hover:text-fg">← Users</Link></p>
      <PageHeader title={u.email} intro={<>{u.name ?? "No name"} · signed up {day(u.created_at)} · last active {day(u.last_active_at)}</>} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Pill tone={u.status === "active" ? "ok" : u.status === "suspended" ? "warn" : "bad"}>{u.status}</Pill>
        <Pill>{u.role}</Pill><Pill>{u.plan}</Pill><Pill>{u.credits} credits</Pill>
        {!data.onboarded && <Pill tone="warn">not onboarded</Pill>}
      </div>
      {notice && <p role="status" className="mb-4 rounded-lg bg-ok-bg px-3 py-2 text-sm text-ok">{notice}</p>}

      {Object.values(data.can).some(Boolean) && (
        <Card className="mb-6">
          <h2 className="font-medium text-fg">Actions</h2>
          <p className="mt-1 text-sm text-muted">Each needs a reason and is recorded in the audit log.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {data.can.credits_adjust && <Button variant="secondary" onClick={() => setAction("credits")}>Adjust credits</Button>}
            {data.can.passes_grant && <Button variant="secondary" onClick={() => setAction("pass")}>Grant a pass</Button>}
            {data.can.users_write && <Button variant="secondary" onClick={() => setAction("signout")}>Sign out everywhere</Button>}
            {data.can.users_write && (u.status === "suspended"
              ? <Button variant="secondary" onClick={() => setAction("unsuspend")}>Unsuspend</Button>
              : <Button variant="danger" onClick={() => setAction("suspend")}>Suspend</Button>)}
            {data.can.users_delete && <Button variant="danger" onClick={() => setAction("delete")}>Delete account</Button>}
          </div>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Account">
          <Facts rows={[["Phone", str(data.phone)], ["User id", u.id],
            ["Sign-in methods", data.providers.map((p) => `${str(p.provider)} (${str(p.email)})`).join(", ") || "—"],
            ["Invited with", data.invited_with ? `${str(data.invited_with.kind)} code ••••${str(data.invited_with.code_hint)}${data.invited_with.campaign ? `, ${str(data.invited_with.campaign)}` : ""}` : "—"],
            ["Referred by", data.referred_by ? `${str(data.referred_by.referrer_email)} (${str(data.referred_by.status)})` : "—"]]} />
        </Section>
        {data.plan ? (
          <Section title="Plan">
            <Facts rows={[["Plan", str(data.plan.kind)], ["Credits", str(data.plan.credits)],
              ["Pass days left", str(data.plan.pass_days_left)], ["Free tailorings left", `${str(data.plan.free_left)} of ${str(data.plan.free_allowance)}`]]} />
          </Section>
        ) : <Section title="Plan"><p className="text-sm text-muted">Billing details need an admin.</p></Section>}
      </div>

      <div className="mt-6 space-y-6">
        <Table title="Tailorings (metadata only)" rows={data.tailorings} cols={[
          ["Started", (r) => day(r.created_at as string)], ["Job", (r) => [r.job_title, r.company].filter(Boolean).join(" at ") || "—"],
          ["ATS", (r) => (r.ats_before === null ? "—" : `${Math.round(r.ats_before as number)} → ${r.ats_after === null ? "—" : Math.round(r.ats_after as number)}`)],
          ["Status", (r) => `${str(r.status)}${r.deleted ? " (deleted)" : r.purged ? " (text cleared)" : ""}`],
          ["Claude", (r) => (r.llm_tailored === null ? "—" : r.llm_tailored ? "yes" : "rules only")],
          ["LLM cost", (r) => `$${(r.llm_cost_usd as number).toFixed(3)}`]]} />
        <Table title="Downloads" rows={data.downloads} cols={[["When", (r) => day(r.created_at as string)], ["Format", (r) => str(r.format)],
          ["Paid with", (r) => `${str(r.paid_with)}${(r.credits as number) > 0 ? ` (${str(r.credits)})` : ""}`], ["File kept", (r) => (r.file_kept ? "yes" : "no")]]} />
        {data.ledger && <Table title="Credit ledger" rows={data.ledger} cols={[["When", (r) => when(r.created_at as string)],
          ["Change", (r) => `${(r.delta as number) > 0 ? "+" : ""}${str(r.delta)}`], ["Reason", (r) => str(r.reason)],
          ["Balance", (r) => str(r.balance_after)], ["Note", (r) => str(r.note)]]} />}
        {data.payments && <Table title="Payments" rows={data.payments} cols={[["When", (r) => day(r.created_at as string)],
          ["Product", (r) => str(r.product_key)], ["Status", (r) => str(r.status)],
          ["Amount", (r) => (r.amount_minor === null ? "—" : `${((r.amount_minor as number) / 100).toFixed(2)} ${str(r.currency)}`)],
          ["Dodo id", (r) => <span className="font-mono text-xs">{str(r.provider_payment_id)}</span>]]} />}
        <Table title="Invites sent" rows={data.invites_sent} cols={[["To", (r) => str(r.email)], ["Sent", (r) => day(r.created_at as string)],
          ["Used", (r) => ((r.uses as number) > 0 ? "yes" : "no")], ["Revoked", (r) => (r.revoked_at ? day(r.revoked_at as string) : "—")]]} />
        <Table title="Referrals" rows={data.referrals} cols={[["Friend", (r) => str(r.referee_email)], ["Status", (r) => str(r.status)],
          ["Why", (r) => str(r.reason)], ["Credits", (r) => str(r.reward_credits)], ["When", (r) => day(r.created_at as string)]]} />
        <Table title="Support tickets" rows={data.tickets} cols={[["Subject", (r) => <Link href={`/admin/support/${str(r.id)}`} className="text-accent hover:underline">{str(r.subject)}</Link>],
          ["Category", (r) => str(r.category)], ["Status", (r) => str(r.status)], ["When", (r) => day(r.created_at as string)]]} />
        {data.audit.length > 0 && <Table title="Audit trail" rows={data.audit} cols={[["When", (r) => when(r.created_at as string)],
          ["Action", (r) => str(r.action)], ["By", (r) => str(r.actor_role)], ["Reason", (r) => str(r.reason)]]} />}
      </div>

      {action && <ActionDialog action={action} user={data} onClose={() => setAction(null)} onDone={done} />}
    </>
  );
}

function ActionDialog({ action, user, onClose, onDone }: { action: Action; user: AdminUserDetail; onClose: () => void; onDone: (m: string) => void }) {
  const id = useId();
  const [delta, setDelta] = useState("");
  const [days, setDays] = useState("");
  const uid = user.user.id;
  const n = Number(delta);
  const common = { onClose };
  switch (action) {
    case "credits":
      return <ReasonDialog {...common} title="Adjust credits" confirm="Apply" valid={Number.isInteger(n) && n !== 0 && Math.abs(n) <= 1000}
        description={`Goes through the ledger as an admin adjustment. Balance now: ${user.user.credits}. It can't go below zero.`}
        extra={<div><Label htmlFor={`${id}-delta`} hint="(+ adds, − removes)">Credits</Label>
          <input id={`${id}-delta`} type="number" step={1} className={inputClass} value={delta} onChange={(e) => setDelta(e.target.value)} /></div>}
        onConfirm={async (reason) => { await attempt(() => adminApi.adjustCredits(uid, n, reason)); onDone(`Credits ${n > 0 ? "added" : "removed"}: ${Math.abs(n)}.`); }} />;
    case "pass":
      return <ReasonDialog {...common} title="Grant a Job Hunt Pass" confirm="Grant pass"
        description="Starts now, or when their current pass ends."
        extra={<div><Label htmlFor={`${id}-days`} hint="(blank: the usual length)">Days</Label>
          <input id={`${id}-days`} type="number" min={1} max={365} className={inputClass} value={days} onChange={(e) => setDays(e.target.value)} /></div>}
        onConfirm={async (reason) => { await attempt(() => adminApi.grantPass(uid, reason, days ? Number(days) : undefined)); onDone("Pass granted."); }} />;
    case "signout":
      return <ReasonDialog {...common} title="Sign out everywhere" confirm="Sign out" description="Ends every session; they can sign in again."
        onConfirm={async (reason) => { await attempt(() => adminApi.signOut(uid, reason)); onDone("Signed out everywhere."); }} />;
    case "suspend":
      return <ReasonDialog {...common} danger title="Suspend this account" confirm="Suspend" description="Signs them out and blocks sign-in until unsuspended."
        onConfirm={async (reason) => { await attempt(() => adminApi.suspend(uid, reason)); onDone("Suspended."); }} />;
    case "unsuspend":
      return <ReasonDialog {...common} title="Unsuspend this account" confirm="Unsuspend"
        onConfirm={async (reason) => { await attempt(() => adminApi.unsuspend(uid, reason)); onDone("Unsuspended."); }} />;
    case "delete":
      return <ReasonDialog {...common} danger title="Delete this account" confirm="Delete for good"
        description="The same erasure the user can do: sign-in methods, sessions, saved resumes, preferences and picture go now; tailoring text follows the retention schedule."
        onConfirm={async (reason) => { await attempt(() => adminApi.deleteUser(uid, reason)); onDone("Account deleted."); }} />;
  }
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <Card><h2 className="mb-3 font-medium text-fg">{title}</h2>{children}</Card>;
}

function Facts({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="min-w-0 break-words text-fg">{v}</dd></div>)}
    </dl>
  );
}

function Table({ title, rows, cols }: { title: string; rows: Rec[]; cols: [string, (r: Rec) => React.ReactNode][] }) {
  return (
    <Section title={`${title} (${rows.length})`}>
      {rows.length === 0 ? <p className="text-sm text-muted">None.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[30rem] text-left text-sm" aria-label={title}>
            <thead className="text-xs text-muted"><tr>{cols.map(([h]) => <th key={h} scope="col" className="py-1 pr-3 font-medium">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-border">
              {rows.map((r, i) => <tr key={str(r.id ?? i)}>{cols.map(([h, f]) => <td key={h} className="py-1.5 pr-3 align-top">{f(r)}</td>)}</tr>)}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
