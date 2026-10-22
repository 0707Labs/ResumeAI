"use client";

import { Suspense, useCallback, useEffect, useId, useState } from "react";

import { type Column, DataTable, Pager, Pill, ReasonDialog, day } from "@/components/admin/ui";
import { ErrorState, PageHeader } from "@/components/app/states";
import { TabList, TabPanel, useTab } from "@/components/app/Tabs";
import { Button, Card, Label, inlineInputClass, inputClass } from "@/components/ui";
import { adminApi, adminError, attempt } from "@/lib/adminApi";
import { api } from "@/lib/api";
import { can } from "@/lib/roles";
import type { AdminInvitePage, AdminInviteRow, AdminSettings, GeneratedCodes, InviteFunnel, Me, WaitlistPage } from "@/lib/schemas";

const TABS = ["codes", "waitlist", "settings", "funnel"] as const;
const LABELS = { codes: "Invite codes", waitlist: "Waitlist", settings: "Settings", funnel: "Funnel" };
const TONE = { active: "ok", exhausted: "neutral", expired: "warn", revoked: "bad" } as const;

export default function AdminInvitesPage() {
  return <Suspense fallback={null}><Invites /></Suspense>;
}

function Invites() {
  const [tab, setTab] = useTab(TABS, "codes");
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => { api.me().then(setMe).catch(() => {}); }, []);
  return (
    <>
      <PageHeader title="Invites" intro="Invite codes, the waitlist, and who gets in." />
      <TabList label="Invite sections" tabs={TABS} labels={LABELS} current={tab} onSelect={setTab} idPrefix="inv" />
      <TabPanel id={tab} idPrefix="inv">
        {tab === "codes" && <Codes />}
        {tab === "waitlist" && <Waitlist />}
        {tab === "settings" && <Settings canEdit={can(me, "settings.write")} />}
        {tab === "funnel" && <Funnel />}
      </TabPanel>
    </>
  );
}

// --- codes ---------------------------------------------------------------------------------------

function Codes() {
  const [filters, setFilters] = useState({ status: "", kind: "", campaign: "", page: 1 });
  const [data, setData] = useState<AdminInvitePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [made, setMade] = useState<GeneratedCodes | null>(null);
  const [acting, setActing] = useState<{ row: AdminInviteRow; kind: "revoke" | "extend" } | null>(null);
  const load = useCallback(() => {
    setData(null);
    adminApi.invites(filters).then(setData).catch((e) => setError(adminError(e)));
  }, [filters]);
  useEffect(load, [load]);

  const columns: Column<AdminInviteRow>[] = [
    { key: "code", label: "Code", render: (i) => <span className="font-mono">••••-••••-{i.code_hint}</span> },
    { key: "kind", label: "Kind", render: (i) => i.kind },
    { key: "campaign", label: "Campaign", render: (i) => i.campaign ?? "—" },
    { key: "uses", label: "Uses", render: (i) => `${i.uses}/${i.max_uses}` },
    { key: "email", label: "Locked to", render: (i) => i.email ?? "—" },
    { key: "bonus", label: "Bonus", render: (i) => (i.bonus_credits ? `+${i.bonus_credits}` : "—") },
    { key: "expires", label: "Expires", render: (i) => day(i.expires_at) },
    { key: "by", label: "Created by", render: (i) => i.created_by_email ?? "—" },
    { key: "status", label: "Status", render: (i) => <Pill tone={TONE[i.status]}>{i.status}</Pill> },
    { key: "actions", label: "", render: (i) => i.status === "revoked" ? null : (
      <span className="flex gap-1">
        <Button variant="ghost" className="min-h-8 px-2" aria-label={`Extend ••••${i.code_hint}`} onClick={() => setActing({ row: i, kind: "extend" })}>Extend</Button>
        <Button variant="ghost" className="min-h-8 px-2 text-bad" aria-label={`Revoke ••••${i.code_hint}`} onClick={() => setActing({ row: i, kind: "revoke" })}>Revoke</Button>
      </span>) },
  ];
  const set = (patch: Partial<typeof filters>) => setFilters((f) => ({ ...f, ...patch, page: patch.page ?? 1 }));

  return (
    <div className="space-y-6">
      <Generate onMade={(g) => { setMade(g); load(); }} />
      {made && <NewCodes made={made} onClose={() => setMade(null)} />}
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Filter by status" className={inlineInputClass} value={filters.status} onChange={(e) => set({ status: e.target.value })}>
          <option value="">Any status</option>{["active", "exhausted", "expired", "revoked"].map((s) => <option key={s}>{s}</option>)}
        </select>
        <select aria-label="Filter by kind" className={inlineInputClass} value={filters.kind} onChange={(e) => set({ kind: e.target.value })}>
          <option value="">Any kind</option>{["admin", "personal", "waitlist"].map((s) => <option key={s}>{s}</option>)}
        </select>
        <input aria-label="Filter by campaign" placeholder="Campaign" className={`${inlineInputClass} w-40`} value={filters.campaign}
          onChange={(e) => set({ campaign: e.target.value })} />
        <a href={adminApi.invitesCsvUrl(filters)} className="ml-auto inline-flex min-h-10 items-center rounded-lg border border-border-strong px-4 text-sm font-medium text-fg hover:bg-surface-2">Export CSV</a>
      </div>
      {error ? <ErrorState message={error} onRetry={load} /> : (
        <>
          <DataTable label="Invite codes" columns={columns} rows={data?.items ?? null} empty="No invites match." />
          {data && <Pager page={data.page} pageSize={data.page_size} total={data.total} onPage={(p) => set({ page: p })} />}
        </>
      )}
      {acting?.kind === "revoke" && <ReasonDialog danger title={`Revoke ••••${acting.row.code_hint}`} confirm="Revoke"
        description={acting.row.kind === "personal" ? "A user's personal invite: if nobody used it, their slot comes back." : "It stops working at once."}
        onClose={() => setActing(null)} onConfirm={async (reason) => { await attempt(() => adminApi.revokeInvite(acting.row.id, reason)); load(); }} />}
      {acting?.kind === "extend" && <ExtendDialog row={acting.row} onClose={() => setActing(null)} onDone={load} />}
    </div>
  );
}

function ExtendDialog({ row, onClose, onDone }: { row: AdminInviteRow; onClose: () => void; onDone: () => void }) {
  const id = useId();
  const [date, setDate] = useState("");
  return <ReasonDialog title={`Extend ••••${row.code_hint}`} confirm="Extend" valid={!!date && new Date(date) > new Date()} onClose={onClose}
    extra={<div><Label htmlFor={`${id}-d`}>New expiry</Label><input id={`${id}-d`} type="date" className={inputClass} value={date} onChange={(e) => setDate(e.target.value)} /></div>}
    onConfirm={async (reason) => { await attempt(() => adminApi.extendInvite(row.id, new Date(`${date}T23:59:59`).toISOString(), reason)); onDone(); }} />;
}

function Generate({ onMade }: { onMade: (g: GeneratedCodes) => void }) {
  const id = useId();
  const [f, setF] = useState({ count: "1", max_uses: "1", expires: "", email: "", bonus: "", campaign: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const field = (k: keyof typeof f) => ({ id: `${id}-${k}`, value: f[k], onChange: (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value }) });
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onMade(await adminApi.generate({
        count: Number(f.count), max_uses: Number(f.max_uses),
        ...(f.expires ? { expires_at: new Date(`${f.expires}T23:59:59`).toISOString() } : {}),
        ...(f.email.trim() ? { email: f.email.trim() } : {}), ...(f.bonus ? { bonus_credits: Number(f.bonus) } : {}),
        ...(f.campaign.trim() ? { campaign: f.campaign.trim() } : {}), ...(f.note.trim() ? { note: f.note.trim() } : {}),
      }));
    } catch (err) {
      setError(adminError(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card as="form" onSubmit={submit} className="space-y-4">
      <h2 className="font-medium text-fg">Generate codes</h2>
      <div className="grid gap-3 sm:grid-cols-3">
        <div><Label htmlFor={`${id}-count`} hint="(1–500)">How many</Label><input type="number" min={1} max={500} required className={inputClass} {...field("count")} /></div>
        <div><Label htmlFor={`${id}-max_uses`}>Uses per code</Label><input type="number" min={1} max={1000} required className={inputClass} {...field("max_uses")} /></div>
        <div><Label htmlFor={`${id}-expires`} hint="(optional)">Expires</Label><input type="date" className={inputClass} {...field("expires")} /></div>
        <div><Label htmlFor={`${id}-email`} hint="(one code only)">Lock to email</Label><input type="email" className={inputClass} {...field("email")} /></div>
        <div><Label htmlFor={`${id}-bonus`} hint="(optional)">Bonus credits</Label><input type="number" min={1} max={100} className={inputClass} {...field("bonus")} /></div>
        <div><Label htmlFor={`${id}-campaign`} hint="(optional)">Campaign</Label><input maxLength={80} className={inputClass} {...field("campaign")} /></div>
      </div>
      <div><Label htmlFor={`${id}-note`} hint="(optional)">Note</Label><input maxLength={200} className={inputClass} {...field("note")} /></div>
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      <Button type="submit" busy={busy}>Generate</Button>
    </Card>
  );
}

function NewCodes({ made, onClose }: { made: GeneratedCodes; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const all = made.codes.join("\n");
  const [csv, setCsv] = useState<string | null>(null);
  useEffect(() => {
    const url = URL.createObjectURL(new Blob([`code\n${all}\n`], { type: "text/csv" }));
    setCsv(url);
    return () => URL.revokeObjectURL(url);
  }, [all]);
  return (
    <Card className="border-accent">
      <h2 className="font-medium text-fg">{made.codes.length} new code{made.codes.length === 1 ? "" : "s"}</h2>
      <p className="mt-1 text-sm text-muted">Copy or download them now: we keep only a fingerprint, so they can&apos;t be shown again.</p>
      <textarea readOnly aria-label="New codes" className={`${inputClass} mt-3 min-h-28 font-mono`} value={all} />
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="secondary" onClick={async () => { try { await navigator.clipboard.writeText(all); setCopied(true); } catch { /* select the text instead */ } }}>
          {copied ? "Copied" : "Copy all"}
        </Button>
        <a href={csv ?? undefined} download={`invite-codes-${made.batch_id.slice(0, 8)}.csv`}
          className="inline-flex min-h-10 items-center rounded-lg border border-border-strong px-4 text-sm font-medium text-fg hover:bg-surface-2">Download CSV</a>
        <Button variant="ghost" onClick={onClose}>Done</Button>
      </div>
    </Card>
  );
}

// --- waitlist ------------------------------------------------------------------------------------

function Waitlist() {
  const [status, setStatus] = useState("waiting");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<WaitlistPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const load = useCallback(() => {
    setData(null);
    setPicked(new Set());
    adminApi.waitlist(status, page).then(setData).catch((e) => setError(adminError(e)));
  }, [status, page]);
  useEffect(load, [load]);

  async function approve() {
    setBusy(true);
    setNotice(null);
    try {
      const r = await adminApi.approveWaitlist([...picked]);
      setNotice(`Invited ${r.approved}.${r.skipped ? ` ${r.skipped} weren't waiting any more.` : ""}${r.failed ? ` ${r.failed} emails failed; those are still waiting.` : ""}`);
      load();
    } catch (e) {
      setError(adminError(e));
    } finally {
      setBusy(false);
    }
  }
  const toggle = (id: string) => setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const rows = data?.items ?? null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Show" className={inlineInputClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          {["waiting", "invited", "converted", "rejected"].map((s) => <option key={s}>{s}</option>)}
        </select>
        {status === "waiting" && (
          <>
            <Button busy={busy} disabled={picked.size === 0} onClick={approve}>Approve and email ({picked.size})</Button>
            <Button variant="secondary" disabled={picked.size === 0} onClick={() => setRejecting(true)}>Reject</Button>
          </>
        )}
      </div>
      {notice && <p role="status" className="rounded-lg bg-ok-bg px-3 py-2 text-sm text-ok">{notice}</p>}
      {error ? <ErrorState message={error} onRetry={load} /> : (
        <>
          <DataTable label="Waitlist" rows={rows} empty="Nobody here." columns={[
            ...(status === "waiting" ? [{ key: "pick", label: "", render: (w: { id: string; email: string }) => (
              <input type="checkbox" aria-label={`Select ${w.email}`} checked={picked.has(w.id)} onChange={() => toggle(w.id)} className="h-4 w-4" />) }] : []),
            { key: "email", label: "Email", render: (w) => w.email },
            { key: "source", label: "Source", render: (w) => w.source ?? "—" },
            { key: "joined", label: "Joined", render: (w) => day(w.created_at) },
            { key: "invited", label: "Invited", render: (w) => day(w.invited_at) },
            { key: "del", label: "", render: (w) => <Button variant="ghost" className="min-h-8 px-2 text-bad" aria-label={`Delete ${w.email}`} onClick={() => setDeleting(w.id)}>Delete</Button> },
          ] as Column<NonNullable<typeof rows>[number]>[]} />
          {data && <Pager page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
        </>
      )}
      {rejecting && <ReasonDialog danger title={`Reject ${picked.size} ${picked.size === 1 ? "person" : "people"}`} confirm="Reject"
        description="They stay on record as rejected and won't be invited." onClose={() => setRejecting(false)}
        onConfirm={async (reason) => { await attempt(() => adminApi.rejectWaitlist([...picked], reason)); load(); }} />}
      {deleting && <ReasonDialog danger title="Delete this entry" confirm="Delete" description="Removes the address from the waitlist. The record of their consent stays."
        onClose={() => setDeleting(null)} onConfirm={async (reason) => { await attempt(() => adminApi.deleteWaitlist(deleting, reason)); load(); }} />}
    </div>
  );
}

// --- settings and funnel -------------------------------------------------------------------------

function Settings({ canEdit }: { canEdit: boolean }) {
  const id = useId();
  const [s, setS] = useState<AdminSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState({ invites_per_user: "", signup_bonus_credits: "" });
  const [pending, setPending] = useState<{ key: "invite_only" | "invites_per_user" | "signup_bonus_credits"; value: boolean | number } | null>(null);
  const load = useCallback(() => {
    adminApi.settings().then((x) => { setS(x); setDraft({ invites_per_user: String(x.values.invites_per_user), signup_bonus_credits: String(x.values.signup_bonus_credits) }); })
      .catch((e) => setError(adminError(e)));
  }, []);
  useEffect(load, [load]);
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!s) return null;
  const v = s.values;
  return (
    <Card className="space-y-5">
      {!canEdit && <p className="text-sm text-muted">Changing these needs a superadmin.</p>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><p className="font-medium text-fg">Invite-only sign-up</p><p className="text-sm text-muted">{v.invite_only ? "On: new accounts need an invite." : "Off: anyone can sign up."}</p></div>
        <Button variant="secondary" disabled={!canEdit} onClick={() => setPending({ key: "invite_only", value: !v.invite_only })}>
          Turn {v.invite_only ? "off" : "on"}
        </Button>
      </div>
      {(["invites_per_user", "signup_bonus_credits"] as const).map((k) => (
        <div key={k} className="flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1">
            <Label htmlFor={`${id}-${k}`} hint={s.overridden.includes(k) ? "(changed here)" : "(from billing.toml)"}>
              {k === "invites_per_user" ? "Invites per user" : "Starter credits for new accounts"}
            </Label>
            <input id={`${id}-${k}`} type="number" min={0} max={100} className={inputClass} disabled={!canEdit}
              value={draft[k]} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />
          </div>
          <Button variant="secondary" disabled={!canEdit || draft[k] === String(v[k]) || draft[k] === ""}
            onClick={() => setPending({ key: k, value: Number(draft[k]) })}>Save</Button>
        </div>
      ))}
      {pending && <ReasonDialog title="Change a setting" confirm="Change"
        description={`${pending.key.replaceAll("_", " ")} → ${String(pending.value)}. Takes effect at once.`}
        onClose={() => setPending(null)} onConfirm={async (reason) => { setS(await attempt(() => adminApi.setSetting(pending.key, pending.value, reason))); }} />}
    </Card>
  );
}

function Funnel() {
  const [days, setDays] = useState(30);
  const [rows, setRows] = useState<InviteFunnel | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setRows(null); adminApi.funnel(days).then(setRows).catch((e) => setError(adminError(e))); }, [days]);
  if (error) return <ErrorState message={error} />;
  const pct = (a: number, b: number) => (b ? `${Math.round((a / b) * 100)}%` : "—");
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="font-medium text-fg">Invites created in the last</h2>
        <select aria-label="Window" className={inlineInputClass} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90, 365].map((d) => <option key={d} value={d}>{d} days</option>)}
        </select>
      </div>
      <DataTable label="Invite funnel" rows={rows?.map((r) => ({ ...r, id: r.kind })) ?? null} empty="No invites yet." columns={[
        { key: "kind", label: "Kind", render: (r) => r.kind },
        { key: "created", label: "Sent", className: "text-right", render: (r) => r.created },
        { key: "redeemed", label: "Redeemed", className: "text-right", render: (r) => `${r.redeemed} (${pct(r.redeemed, r.created)})` },
        { key: "first", label: "First tailoring", className: "text-right", render: (r) => `${r.first_tailoring} (${pct(r.first_tailoring, r.redeemed)})` },
      ]} />
    </Card>
  );
}
