"use client";

import { useCallback, useEffect, useState } from "react";

import { AuthErrorAlert } from "@/components/auth/AuthCard";
import { Alert, Button, Card } from "@/components/ui";
import { api } from "@/lib/api";
import { can } from "@/lib/roles";
import { REASON_TEXT, adminReferralsApi } from "@/lib/referrals";
import type { AdminReferrals, Me } from "@/lib/schemas";

const when = (iso: string) => new Date(iso).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" });

/** Referral review queue: flagged sign-ups to approve or reject, and paid ones to reverse. */
export default function AdminReferralsPage() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [view, setView] = useState<"review" | "recent">("review");
  const [rows, setRows] = useState<AdminReferrals | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => { api.me().then(setMe).catch(() => setMe(null)); }, []);
  const load = useCallback(() => {
    setError(null);
    adminReferralsApi.queue(view).then(setRows).catch(setError);
  }, [view]);
  useEffect(() => { if (can(me, "referrals.decide")) load(); }, [me, load]);

  if (me === undefined) return null;
  if (!can(me, "referrals.decide")) return <Alert tone="info" title="Not available for your role">Referral decisions need an admin.</Alert>;

  async function act(id: string, fn: () => Promise<unknown>) {
    setBusy(id);
    try { await fn(); load(); } catch (e) { setError(e); } finally { setBusy(null); }
  }
  const ask = (what: string) => window.prompt(`Why ${what}? (kept on the referral)`)?.trim() || null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Referrals</h1>
          <p className="mt-1 text-muted">Approve or reject flagged sign-ups; reverse a reward that shouldn&apos;t have been paid.</p>
        </div>
        <div role="tablist" aria-label="View" className="flex rounded-lg border border-border p-0.5">
          {(["review", "recent"] as const).map((v) => (
            <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
              className={`rounded-md px-3 py-1.5 text-sm ${view === v ? "bg-surface-2 font-medium text-fg" : "text-muted"}`}>
              {v === "review" ? "Needs review" : "Recent"}
            </button>
          ))}
        </div>
      </div>
      <AuthErrorAlert error={error} />
      <Card>
        {!rows ? <p className="text-muted">Loading…</p> : rows.length === 0 ? (
          <p className="text-muted">{view === "review" ? "Nothing waiting for review." : "No referrals yet."}</p>
        ) : (
          <ul className="divide-y divide-border">
            {rows.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
                <div className="min-w-0 space-y-0.5">
                  <p><span className="font-medium">{r.referrer_email}</span> referred <span className="font-medium">{r.referee_email}</span></p>
                  <p className="text-muted">
                    {when(r.created_at)} · {r.status}{r.reason && ` · ${REASON_TEXT[r.reason] ?? r.reason}`}
                    {r.same_network > 1 && ` · ${r.same_network} sign-ups from one network`}
                    {r.used_as_invite && " · used as invite"}
                    {r.reversed_at && " · reversed"}
                  </p>
                </div>
                <div className="flex gap-2">
                  {r.status === "pending" && r.needs_review && (
                    <>
                      <Button className="min-h-9 px-3" busy={busy === r.id}
                        onClick={() => void act(r.id, () => adminReferralsApi.approve(r.id))}>Approve</Button>
                      <Button variant="secondary" className="min-h-9 px-3" disabled={busy === r.id}
                        onClick={() => { const why = ask("reject it"); if (why) void act(r.id, () => adminReferralsApi.reject(r.id, why)); }}>
                        Reject
                      </Button>
                    </>
                  )}
                  {r.status === "rewarded" && (
                    <Button variant="danger" className="min-h-9 px-3" busy={busy === r.id}
                      onClick={() => { const why = ask("reverse it"); if (why) void act(r.id, () => adminReferralsApi.reverse(r.id, why)); }}>
                      Reverse
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
