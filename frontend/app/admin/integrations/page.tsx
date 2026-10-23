"use client";

import { useCallback, useEffect, useState } from "react";

import { DataTable, Pager, Pill, ReasonDialog, when, type Column } from "@/components/admin/ui";
import { ErrorState, PageHeader, Skeleton } from "@/components/app/states";
import { Alert, Button, Card, Label, inlineInputClass } from "@/components/ui";
import { adminApi, adminError, attempt } from "@/lib/adminApi";
import { api } from "@/lib/api";
import { can } from "@/lib/roles";
import type { AdminSettings, Integration, Me, WebhookRow } from "@/lib/schemas";

const TITLE: Record<string, string> = {
  anthropic: "Claude (Anthropic API)", database: "Database (Postgres)", dodo: "Dodo Payments", email: "Email",
  google: "Google sign-in", github: "GitHub sign-in", slack: "Slack alerts", error_monitoring: "Error monitoring",
  analytics: "Analytics",
};
const STATUS: Record<Integration["status"], { label: string; tone: "ok" | "warn" | "bad" | "neutral" }> = {
  healthy: { label: "Healthy", tone: "ok" }, degraded: { label: "Degraded", tone: "warn" }, failing: { label: "Failing", tone: "bad" },
  configured: { label: "Configured, not checked", tone: "neutral" }, not_configured: { label: "Not configured", tone: "neutral" },
};
const STEPS: [string, string][] = [["gap_analysis", "Gap analysis"], ["tailor", "Tailoring"], ["tailor_repair", "Tailoring repair"],
  ["ats_semantic", "ATS semantic match"], ["mentor", "Mentor questions"]];
const DEFAULT_MODEL = { model: "claude-opus-5-5", max_tokens: 16000, effort: "medium" as const };

/** Words for a fact's key, and a readable value. */
const factLabel = (k: string) => k.replaceAll("_", " ").replace(/\b24h\b/, "(24 h)").replace(/\b7d\b/, "(7 days)");
function factValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return when(v);
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if ("code" in o || "status" in o) return [o.status, o.code, o.at ? when(String(o.at)) : null].filter(Boolean).join(" · ");
    const entries = Object.entries(o);
    return entries.length ? entries.map(([k, x]) => `${k}: ${typeof x === "object" && x ? Object.values(x).join(" / ") : String(x)}`).join("; ") : "—";
  }
  return String(v);
}

export default function AdminIntegrationsPage() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [cards, setCards] = useState<Integration[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.me().then(setMe).catch(() => setMe(null)); }, []);
  const load = useCallback(() => {
    setError(null);
    adminApi.integrations().then(setCards).catch((e) => setError(adminError(e)));
  }, []);
  useEffect(() => { if (can(me, "integrations.read")) load(); }, [me, load]);

  if (me === undefined) return null;
  if (!can(me, "integrations.read")) return <Alert tone="info" title="Not available for your role">Integrations need an admin.</Alert>;

  return (
    <div className="space-y-6">
      <PageHeader title="Integrations" intro="What the app is connected to and whether it works. Secrets are set in the server's environment, never here; this page shows only whether each is set." />
      {error && <ErrorState message={error} onRetry={load} />}
      {!cards && !error && <div className="grid gap-4 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-48" />)}</div>}
      {cards && (
        <ul className="grid gap-4 md:grid-cols-2" aria-label="Integrations">
          {cards.map((c) => <IntegrationCard key={c.name} card={c} onChecked={(next) => setCards((all) => all && all.map((x) => x.name === next.name ? next : x))} />)}
        </ul>
      )}
      <Models canEdit={can(me, "settings.write")} />
      <Webhooks canReplay={can(me, "billing.write")} />
    </div>
  );
}

function IntegrationCard({ card, onChecked }: { card: Integration; onChecked: (c: Integration) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const s = STATUS[card.status];
  async function check() {
    setBusy(true);
    setError(null);
    try {
      const r = await adminApi.check(card.name);
      onChecked({ ...card, ...r, status: r.status });
    } catch (e) {
      setError(adminError(e));
    } finally {
      setBusy(false);
    }
  }
  const facts = Object.entries({ ...card.facts, ...card.check_detail }).filter(([k]) => k !== "note");
  const note = card.facts.note as string | undefined;
  return (
    <li className="space-y-3 rounded-xl border border-border bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h2 className="font-semibold text-fg">{TITLE[card.name] ?? card.name}</h2>
        <Pill tone={s.tone}>{s.label}</Pill>
      </div>
      {note && <p className="text-sm text-muted">{note}</p>}
      {(card.checked_at || card.error_code) && (
        <p className="text-xs text-muted">
          {card.checked_at && <>Checked {when(card.checked_at)}</>}
          {card.last_ok_at && <> · last passed {when(card.last_ok_at)}</>}
          {card.error_code && <> · <span className="font-mono text-bad">{card.error_code}</span></>}
        </p>
      )}
      {facts.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          {facts.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted">{factLabel(k)}</dt>
              <dd className="min-w-0 break-words text-fg">{factValue(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {card.secrets.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label={`${TITLE[card.name] ?? card.name} secrets`}>
          {card.secrets.map((x) => (
            <li key={x.name}><Pill tone={x.set ? "neutral" : "warn"}>
              <span className="font-mono">{x.name}</span>&nbsp;{x.set ? (x.hint ? `set ${x.hint}` : "set") : "not set"}
            </Pill></li>
          ))}
        </ul>
      )}
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {card.checkable && card.status !== "not_configured" && (
        <Button variant="secondary" className="min-h-9 px-3" busy={busy} onClick={() => void check()}>Run health check</Button>
      )}
    </li>
  );
}

type StepModel = AdminSettings["values"]["llm_models"][string];

/** Which Claude model each pipeline step uses (superadmin). Only priced models can be chosen. */
function Models({ canEdit }: { canEdit: boolean }) {
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [allowed, setAllowed] = useState<string[]>([]);
  const [draft, setDraft] = useState<Record<string, StepModel>>({});
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<"save" | "reset" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const sync = (s: AdminSettings) => { setSettings(s); setDraft(s.values.llm_models); };
  useEffect(() => {
    Promise.all([adminApi.settings(), adminApi.config()])
      .then(([s, c]) => { sync(s); setAllowed(c.llm_prices); })
      .catch((e) => setError(adminError(e)));
  }, []);
  if (error) return <ErrorState message={error} />;
  if (!settings) return null;
  const saved = settings.values.llm_models;
  const changed = JSON.stringify(draft) !== JSON.stringify(saved);
  const set = (step: string, patch: Partial<StepModel> | null) => setDraft((d) => {
    const next = { ...d };
    if (patch === null) delete next[step]; else next[step] = { ...(d[step] ?? DEFAULT_MODEL), ...patch };
    return next;
  });
  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Models per step</h2>
        <p className="text-sm text-muted">
          A step set to Default uses {DEFAULT_MODEL.model} with {DEFAULT_MODEL.max_tokens.toLocaleString("en")} max tokens and the
          step&apos;s own effort. The client sets effort, not temperature. If a chosen model stops working, calls fall back to rules-only for that step.
          {!canEdit && " Changing these needs a superadmin."}
        </p>
      </div>
      {notice && <p role="status" className="rounded-lg bg-ok-bg px-3 py-2 text-sm text-ok">{notice}</p>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-left text-sm" aria-label="Models per step">
          <thead className="text-xs text-muted"><tr>
            <th scope="col" className="py-1 font-medium">Step</th><th scope="col" className="py-1 font-medium">Model</th>
            <th scope="col" className="py-1 font-medium">Max tokens</th><th scope="col" className="py-1 font-medium">Effort</th>
          </tr></thead>
          <tbody className="divide-y divide-border">
            {STEPS.map(([step, label]) => {
              const row = draft[step];
              return (
                <tr key={step}>
                  <td className="py-2 pr-2">{label}</td>
                  <td className="py-2 pr-2">
                    <select aria-label={`${label} model`} className={inlineInputClass} disabled={!canEdit} value={row?.model ?? ""}
                      onChange={(e) => set(step, e.target.value ? { model: e.target.value } : null)}>
                      <option value="">Default</option>
                      {allowed.map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                  </td>
                  <td className="py-2 pr-2">
                    <input aria-label={`${label} max tokens`} type="number" min={1024} max={64000} step={1024} className={`${inlineInputClass} w-28`}
                      disabled={!canEdit || !row} value={row?.max_tokens ?? ""} onChange={(e) => set(step, { max_tokens: Number(e.target.value) })} />
                  </td>
                  <td className="py-2">
                    <select aria-label={`${label} effort`} className={inlineInputClass} disabled={!canEdit || !row} value={row?.effort ?? ""}
                      onChange={(e) => set(step, { effort: e.target.value as StepModel["effort"] })}>
                      {!row && <option value="">—</option>}
                      <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
                    </select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <div className="flex flex-wrap gap-2">
          <Button disabled={!changed} onClick={() => setPending("save")}>Save models</Button>
          {settings.overridden.includes("llm_models") && <Button variant="ghost" onClick={() => setPending("reset")}>Back to defaults</Button>}
        </div>
      )}
      {pending && (
        <ReasonDialog title={pending === "save" ? "Change the models" : "Use the default models"} confirm={pending === "save" ? "Save" : "Reset"}
          description="Takes effect within 30 seconds for new Claude calls. The change is audited."
          onClose={() => setPending(null)}
          onConfirm={async (reason) => {
            sync(await attempt(() => pending === "save" ? adminApi.setSetting("llm_models", draft, reason) : adminApi.resetSetting("llm_models", reason)));
            setNotice("Saved.");
          }} />
      )}
    </Card>
  );
}

const FILTERS = [["failing", "Failing"], ["all", "All"], ["processed", "Processed"], ["ignored", "Ignored"], ["flagged", "Flagged"]] as const;

/** Recent Dodo deliveries; a failing one can be replayed from its stored, verified data. */
function Webhooks({ canReplay }: { canReplay: boolean }) {
  const [status, setStatus] = useState<string>("failing");
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<{ items: WebhookRow[]; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replaying, setReplaying] = useState<WebhookRow | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    adminApi.webhooks(status, page).then((r) => setRows({ items: r.items, total: r.total })).catch((e) => setError(adminError(e)));
  }, [status, page]);
  useEffect(() => { load(); }, [load]);
  const columns: Column<WebhookRow>[] = [
    { key: "received", label: "Received", render: (w) => when(w.received_at) },
    { key: "type", label: "Event", render: (w) => <span className="font-mono text-xs">{w.event_type}</span> },
    { key: "status", label: "Status", render: (w) => (
      <Pill tone={w.status === "failing" ? "bad" : w.status === "flagged" ? "warn" : w.status === "processed" ? "ok" : "neutral"}>{w.status}</Pill>) },
    { key: "failures", label: "Failures", className: "text-right tabular-nums", render: (w) => w.failures || "—" },
    { key: "error", label: "Last error", render: (w) => w.last_error ? <span className="font-mono text-xs">{w.last_error}</span> : "—" },
    ...(canReplay ? [{ key: "replay", label: "", className: "text-right", render: (w: WebhookRow) => w.replayable ? (
      <Button variant="secondary" className="min-h-8 px-2 text-xs" aria-label={`Replay ${w.event_type} ${w.id}`}
        onClick={() => { setNotice(null); setReplaying(w); }}>Replay</Button>) : null }] : []),
  ];
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Webhook log</h2>
          <p className="text-sm text-muted">Dodo retries failures on its own. A replay runs a failed event again here; an event is never applied twice.</p>
        </div>
        <div>
          <Label htmlFor="wh-status">Show</Label>
          <select id="wh-status" className={inlineInputClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            {FILTERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
      </div>
      {notice && <p role="status" className="rounded-lg bg-ok-bg px-3 py-2 text-sm text-ok">{notice}</p>}
      {error ? <ErrorState message={error} onRetry={load} /> : (
        <>
          <DataTable label="Webhook events" columns={columns} rows={rows?.items ?? null}
            empty={status === "failing" ? "No failing events." : "No events yet."} />
          {rows && rows.total > 0 && <Pager page={page} pageSize={25} total={rows.total} onPage={setPage} />}
        </>
      )}
      {replaying && (
        <ReasonDialog title="Replay webhook" confirm="Replay" description={<>Runs <span className="font-mono">{replaying.event_type}</span> again from the data stored when it failed.</>}
          onClose={() => setReplaying(null)}
          onConfirm={async (reason) => {
            const r = await attempt(() => adminApi.replay(replaying.id, reason));
            setNotice(r.outcome === "failed" ? "It failed again; the error is in the log." : `Replayed: ${r.outcome}.`);
            load();
          }} />
      )}
    </Card>
  );
}
