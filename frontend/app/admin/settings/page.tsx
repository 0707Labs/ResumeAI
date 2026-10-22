"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Pill, ReasonDialog, day, when } from "@/components/admin/ui";
import { ErrorState, PageHeader } from "@/components/app/states";
import { Alert, Button, Card, Label, inlineInputClass, inputClass } from "@/components/ui";
import { adminApi, adminError, attempt } from "@/lib/adminApi";
import { api } from "@/lib/api";
import { formatMoney } from "@/lib/billing";
import { ROLE_LABEL, can } from "@/lib/roles";
import type { AdminConfig, AdminSettings, AuditEntry, Me, SettingKey, StaffMember } from "@/lib/schemas";

/** Superadmin settings, and the audit log for every admin. */
export default function AdminSettingsPage() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => { api.me().then(setMe).catch(() => setMe(null)); }, []);
  if (me === undefined) return null;
  if (!me || !can(me, "audit.read")) return <Alert tone="info" title="Not available for your role">Settings need an admin.</Alert>;
  const superadmin = can(me, "settings.write");
  return (
    <div className="space-y-6">
      <PageHeader title="Settings" intro={superadmin
        ? "Changes apply at once. Each one asks for a reason, may ask you to sign in again, and is recorded in the audit log."
        : "Read-only for your role: changing settings and roles needs a superadmin."} />
      <Flags canEdit={superadmin} />
      <Plans />
      <Staff me={me} canEdit={can(me, "roles.write")} />
      <AuditLog />
    </div>
  );
}

// --- flags ---------------------------------------------------------------------------------------

type FlagKey = Extract<SettingKey, "invite_only" | "referrals_enabled" | "pro_enabled" | "free_analyses_per_month" | "maintenance_banner">;
const FLAGS: { key: FlagKey; label: string; help: string; kind: "bool" | "int" | "text" }[] = [
  { key: "invite_only", label: "Invite-only sign-up", help: "New accounts need an invite; others join the waitlist.", kind: "bool" },
  { key: "pro_enabled", label: "Pro plan on sale", help: "Shows Pro on the pricing page and allows its checkout.", kind: "bool" },
  { key: "referrals_enabled", label: "Referral rewards", help: "Rules live on the Referrals page.", kind: "bool" },
  { key: "free_analyses_per_month", label: "Free tailorings a month", help: "Per account, reset on the 1st (UTC).", kind: "int" },
  { key: "maintenance_banner", label: "Maintenance banner", help: "Shown at the top of every page. Leave empty for none.", kind: "text" },
];
const show = (v: unknown) => (v === true ? "On" : v === false ? "Off" : v === null || v === "" ? "None" : String(v));

function Flags({ canEdit }: { canEdit: boolean }) {
  const [s, setS] = useState<AdminSettings | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ key: FlagKey; value: unknown; reset?: boolean } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const sync = (x: AdminSettings) => {
    setS(x);
    setDraft(Object.fromEntries(FLAGS.map((f) => [f.key, x.values[f.key] === null ? "" : String(x.values[f.key])])));
  };
  useEffect(() => { adminApi.settings().then(sync).catch((e) => setError(adminError(e))); }, []);
  if (error) return <ErrorState message={error} />;
  if (!s) return null;
  const parse = (f: (typeof FLAGS)[number]) => f.kind === "bool" ? draft[f.key] === "true" : f.kind === "int" ? Number(draft[f.key])
    : draft[f.key].trim() || null;
  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Feature flags</h2>
        <p className="text-sm text-muted">The kill switch and budgets are on the <Link href="/admin/costs" className="underline">Costs</Link> page.</p>
      </div>
      {notice && <p role="status" className="rounded-lg bg-ok-bg px-3 py-2 text-sm text-ok">{notice}</p>}
      <ul className="divide-y divide-border">
        {FLAGS.map((f) => {
          const id = `flag-${f.key}`;
          const changed = draft[f.key] !== (s.values[f.key] === null ? "" : String(s.values[f.key]));
          const valid = f.kind !== "int" || (draft[f.key] !== "" && Number(draft[f.key]) >= 0 && Number(draft[f.key]) <= 100);
          return (
            <li key={f.key} className="grid gap-2 py-3 sm:grid-cols-[1fr_auto] sm:items-end">
              <div>
                <Label htmlFor={id} hint={s.overridden.includes(f.key) ? `(default: ${show(s.defaults[f.key])})` : "(default)"}>{f.label}</Label>
                {f.kind === "bool" ? (
                  <select id={id} className={inputClass} disabled={!canEdit} value={draft[f.key]}
                    onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}>
                    <option value="true">On</option><option value="false">Off</option>
                  </select>
                ) : (
                  <input id={id} className={inputClass} disabled={!canEdit} type={f.kind === "int" ? "number" : "text"}
                    min={0} max={100} maxLength={280} value={draft[f.key]} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
                )}
                <p className="mt-1 text-xs text-muted">{f.help}</p>
              </div>
              {canEdit && (
                <div className="flex gap-2">
                  <Button variant="secondary" disabled={!changed || !valid} onClick={() => setPending({ key: f.key, value: parse(f) })}>Save</Button>
                  {s.overridden.includes(f.key) && (
                    <Button variant="ghost" onClick={() => setPending({ key: f.key, value: s.defaults[f.key], reset: true })}>Default</Button>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {pending && (
        <ReasonDialog title={pending.reset ? "Back to the default" : "Change a setting"} confirm={pending.reset ? "Reset" : "Change"}
          description={`${FLAGS.find((f) => f.key === pending.key)?.label}: ${show(pending.value)}`}
          onClose={() => setPending(null)}
          onConfirm={async (reason) => {
            sync(await attempt(() => pending.reset ? adminApi.resetSetting(pending.key, reason)
              : adminApi.setSetting(pending.key, pending.value, reason)));
            setNotice("Saved.");
          }} />
      )}
    </Card>
  );
}

// --- plans and pricing (read-only) ------------------------------------------------------------------

function Plans() {
  const [c, setC] = useState<AdminConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { adminApi.config().then(setC).catch((e) => setError(adminError(e))); }, []);
  if (error) return <ErrorState message={error} />;
  if (!c) return null;
  const current = c.notices.filter((n) => n.current);
  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Plans and pricing</h2>
        <p className="text-sm text-muted">From billing.toml (change it there and redeploy; purchases keep the terms they were bought on).</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-left text-sm" aria-label="Products">
          <thead className="text-xs text-muted"><tr>
            <th scope="col" className="py-1 font-medium">Product</th><th scope="col" className="py-1 font-medium">What it gives</th>
            <th scope="col" className="py-1 font-medium">Prices</th><th scope="col" className="py-1 font-medium">On sale</th>
          </tr></thead>
          <tbody className="divide-y divide-border">
            {c.products.map((p) => (
              <tr key={p.key}>
                <td className="py-1.5">{p.name} <span className="font-mono text-xs text-muted">{p.key}</span></td>
                <td className="py-1.5">{p.credits ? `${p.credits} credits` : p.pass_days ? `${p.pass_days} days, fair use ${p.fair_use_cap}`
                  : p.interval ? `Per ${p.interval}, fair use ${p.fair_use_cap}` : "—"}</td>
                <td className="py-1.5 tabular-nums">{Object.entries(p.prices).map(([cur, minor]) => formatMoney(minor, cur)).join(" · ")}</td>
                <td className="py-1.5">{p.enabled ? <Pill tone="ok">Yes</Pill> : <Pill>No</Pill>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-3">
        <div><dt className="text-muted">Free tailorings a month</dt><dd className="font-medium">{c.free_analyses_per_month}</dd></div>
        <div><dt className="text-muted">Credits per download</dt><dd className="font-medium">{c.credits_per_download}</dd></div>
        <div><dt className="text-muted">Free re-download window</dt><dd className="font-medium">{c.redownload_free_days} days</dd></div>
        <div><dt className="text-muted">Claude analyses a day</dt><dd className="font-medium">{c.claude_per_day.free} free · {c.claude_per_day.paid} paid</dd></div>
        <div><dt className="text-muted">Resume text kept</dt><dd className="font-medium">{c.retention.analysis_days} days</dd></div>
        <div><dt className="text-muted">Final resume kept</dt>
          <dd className="font-medium">{c.retention.download_days ? `${c.retention.download_days} days` : "the re-download window"}</dd></div>
      </dl>
      <div>
        <h3 className="mb-1 text-sm font-semibold">Legal versions in force</h3>
        <p className="mb-2 text-xs text-muted">
          Publish a new version with <code>python -m app.auth.cli publish-notice</code> (it hashes the exact text people see),
          not from here.
        </p>
        {current.length === 0 ? <p className="text-sm text-muted">No notices published.</p> : (
          <ul className="flex flex-wrap gap-2 text-sm" aria-label="Legal versions">
            {current.map((n) => (
              <li key={`${n.purpose}-${n.language}`}><Pill>{n.purpose} {n.version} ({n.language}) · {day(n.published_at)}</Pill></li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

// --- staff -----------------------------------------------------------------------------------------

const ROLES = ["user", "support", "admin", "superadmin"] as const;

function Staff({ me, canEdit }: { me: Me; canEdit: boolean }) {
  const [staff, setStaff] = useState<StaffMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ id: string; email: string; role: string } | null>(null);
  const [email, setEmail] = useState("");
  const [lookup, setLookup] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(() => { adminApi.staff().then(setStaff).catch((e) => setError(adminError(e))); }, []);
  useEffect(() => { load(); }, [load]);

  async function promote(e: React.FormEvent) {
    e.preventDefault();
    setLookup(null);
    const wanted = email.trim().toLowerCase();
    try {
      const found = (await adminApi.users({ q: wanted })).items.find((u) => u.email.toLowerCase() === wanted);
      if (!found) setLookup("No account with that email. They need to sign up first.");
      else setPending({ id: found.id, email: found.email, role: "support" });
    } catch (err) {
      setLookup(adminError(err));
    }
  }

  if (error) return <ErrorState message={error} />;
  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Staff</h2>
        <p className="text-sm text-muted">Nobody can change their own role, and the last superadmin can&apos;t be demoted.</p>
      </div>
      {notice && <p role="status" className="rounded-lg bg-ok-bg px-3 py-2 text-sm text-ok">{notice}</p>}
      {!staff ? <p className="text-sm text-muted">Loading…</p> : (
        <ul className="divide-y divide-border text-sm" aria-label="Staff">
          {staff.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span className="min-w-0">
                <Link href={`/admin/users/${s.id}`} className="font-medium text-accent underline">{s.email}</Link>
                <span className="ml-2 text-xs text-muted">last sign-in {s.last_login_at ? when(s.last_login_at) : "never"}</span>
              </span>
              {canEdit && s.id !== me.id ? (
                <select aria-label={`Role for ${s.email}`} className={inlineInputClass} value={s.role}
                  onChange={(e) => setPending({ id: s.id, email: s.email, role: e.target.value })}>
                  {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                </select>
              ) : <Pill>{ROLE_LABEL[s.role]}</Pill>}
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <form onSubmit={promote} className="flex flex-wrap items-end gap-2">
          <div>
            <Label htmlFor="promote-email">Add staff by email</Label>
            <input id="promote-email" type="email" required className={inlineInputClass} value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <Button type="submit" variant="secondary" className="min-h-10">Find</Button>
          {lookup && <p role="alert" className="w-full text-sm text-bad">{lookup}</p>}
        </form>
      )}
      {pending && (
        <ReasonDialog title="Change role" confirm="Change role" danger={pending.role === "superadmin"}
          valid={ROLES.includes(pending.role as (typeof ROLES)[number])}
          description={`${pending.email} becomes ${ROLE_LABEL[pending.role as (typeof ROLES)[number]]}.`}
          extra={
            <div>
              <Label htmlFor="new-role">Role</Label>
              <select id="new-role" className={inputClass} value={pending.role} onChange={(e) => setPending({ ...pending, role: e.target.value })}>
                {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
            </div>
          }
          onClose={() => { setPending(null); load(); }}
          onConfirm={async (reason) => {
            await attempt(() => adminApi.setRole(pending.id, pending.role, reason));
            setNotice(`${pending.email} is now ${ROLE_LABEL[pending.role as (typeof ROLES)[number]]}.`);
            setEmail("");
          }} />
      )}
    </Card>
  );
}

// --- audit log -------------------------------------------------------------------------------------

type AuditFilters = { action: string; target_type: string; target_id: string; since: string; until: string };
const summary = (o: Record<string, unknown> | null) =>
  o ? Object.entries(o).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join(", ") : "";

function AuditLog() {
  const empty: AuditFilters = { action: "", target_type: "", target_id: "", since: "", until: "" };
  const [form, setForm] = useState<AuditFilters>(empty);
  const [applied, setApplied] = useState<AuditFilters>(empty);
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const query = useCallback((before_id?: number) => adminApi.audit({
    action: applied.action || undefined, target_type: applied.target_type || undefined, target_id: applied.target_id || undefined,
    since: applied.since ? new Date(`${applied.since}T00:00:00Z`).toISOString() : undefined,
    until: applied.until ? new Date(Date.parse(`${applied.until}T00:00:00Z`) + 86_400_000).toISOString() : undefined, before_id,
  }), [applied]);
  useEffect(() => {
    setEntries(null);
    setError(null);
    query().then((p) => { setEntries(p.entries); setNext(p.next_before_id); }).catch((e) => setError(adminError(e)));
  }, [query]);
  async function older() {
    if (next === null) return;
    try {
      const p = await query(next);
      setEntries((e) => [...(e ?? []), ...p.entries]);
      setNext(p.next_before_id);
    } catch (e) {
      setError(adminError(e));
    }
  }
  const field = (k: keyof AuditFilters, label: string, type = "text") => (
    <div>
      <Label htmlFor={`audit-${k}`}>{label}</Label>
      <input id={`audit-${k}`} type={type} className={inlineInputClass} value={form[k]} maxLength={64}
        onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
    </div>
  );
  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Audit log</h2>
        <p className="text-sm text-muted">Every staff change, newest first. Append-only: nobody can edit or delete it.</p>
      </div>
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); setApplied(form); }}>
        {field("action", "Action (e.g. settings.update)")}
        {field("target_type", "Target type")}
        {field("target_id", "Target id")}
        {field("since", "From", "date")}
        {field("until", "To", "date")}
        <Button type="submit" variant="secondary" className="min-h-10">Filter</Button>
        <Button variant="ghost" className="min-h-10" onClick={() => { setForm(empty); setApplied(empty); }}>Clear</Button>
      </form>
      {error && <ErrorState message={error} />}
      {!entries ? <p className="text-sm text-muted">Loading…</p> : entries.length === 0 ? <p className="text-sm text-muted">Nothing matches.</p> : (
        <ol className="divide-y divide-border text-sm" aria-label="Audit entries">
          {entries.map((a) => (
            <li key={a.id} className="space-y-0.5 py-2">
              <p><span className="font-mono text-xs">{a.action}</span>
                {a.target_type && <span className="text-muted"> · {a.target_type} {a.target_id}</span>}</p>
              <p className="text-xs text-muted">{when(a.created_at)} · {a.actor_email ?? "system"} ({a.actor_role}){a.reason && <> · “{a.reason}”</>}</p>
              {(a.before || a.after) && (
                <p className="break-words text-xs text-muted">{summary(a.before) || "—"} → {summary(a.after) || "—"}</p>
              )}
            </li>
          ))}
        </ol>
      )}
      {next !== null && <Button variant="secondary" onClick={() => void older()}>Older entries</Button>}
    </Card>
  );
}
