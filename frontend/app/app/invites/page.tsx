"use client";

import { useCallback, useEffect, useId, useState } from "react";

import { EmptyState, ErrorState, LoadingStatus, PageHeader, Skeleton } from "@/components/app/states";
import { CheckIcon, ErrorIcon, InfoIcon, MailIcon } from "@/components/icons";
import { Alert, Button, Card, Label, inputClass } from "@/components/ui";
import type { Invites } from "@/lib/schemas";
import { userApi, userError } from "@/lib/user";

const day = (iso: string) => new Date(iso).toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" });
const credits = (n: number) => `${n} credit${n === 1 ? "" : "s"}`;
type Status = Invites["invitees"][number]["status"];

const STATUS: Record<Status, { word: string; Icon: typeof CheckIcon; cls: string }> = {
  sent: { word: "Invite sent", Icon: MailIcon, cls: "bg-surface-2 text-fg" },
  expired: { word: "Expired, not used", Icon: InfoIcon, cls: "bg-surface-2 text-muted" },
  revoked: { word: "Revoked", Icon: InfoIcon, cls: "bg-surface-2 text-muted" },
  joined: { word: "Joined", Icon: CheckIcon, cls: "bg-surface-2 text-fg" },
  first_tailoring: { word: "First tailoring done", Icon: CheckIcon, cls: "bg-surface-2 text-fg" },
  rewarded: { word: "Rewarded", Icon: CheckIcon, cls: "bg-ok-bg text-ok" },
  not_eligible: { word: "Not rewarded", Icon: ErrorIcon, cls: "bg-bad-bg text-bad" },
};

/** Invites & Referrals: your link and code, email invites within your quota, and how
 * each friend is getting on. */
export default function InvitesPage() {
  const [data, setData] = useState<Invites | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    userApi.invites().then(setData).catch((e) => setError(userError(e)));
  }, []);
  useEffect(load, [load]);

  if (error && !data) return <><PageHeader title="Invites & Referrals" /><ErrorState message={error} onRetry={load} /></>;
  if (!data) {
    return <><LoadingStatus label="Loading your invites" /><Skeleton className="mb-6 h-8 w-64" />
      <div className="space-y-4"><Skeleton className="h-28" /><Skeleton className="h-40" /></div></>;
  }
  const earnedWhen = data.trigger === "on_first_tailoring" ? "once they finish their first tailoring" : "as soon as they join";
  return (
    <div className="space-y-6">
      <PageHeader title="Invites & Referrals"
        intro={data.enabled
          ? <>Invite friends by email or share your link. You get {credits(data.reward_credits)} for each friend {earnedWhen}.</>
          : "Invite friends by email or share your link."} />
      {!data.enabled && <Alert tone="warn" title="Rewards are paused">Invites still work, but nothing is rewarded right now.</Alert>}

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <p className="text-sm text-muted">Invites left</p>
          <p className="mt-1 text-2xl font-semibold text-fg">{data.left} <span className="text-base font-normal text-muted">of {data.limit}</span></p>
          <div className="mt-3 h-2 rounded-full bg-surface-2" role="progressbar" aria-label="Invites used"
            aria-valuemin={0} aria-valuemax={data.limit} aria-valuenow={data.used}>
            <div className="h-2 rounded-full bg-accent" style={{ width: `${Math.min(100, (data.used / Math.max(data.limit, 1)) * 100)}%` }} />
          </div>
        </Card>
        <Card><p className="text-sm text-muted">Friends joined</p>
          <p className="mt-1 text-2xl font-semibold text-fg">{data.invitees.filter((i) => !["sent", "expired", "revoked"].includes(i.status)).length}</p></Card>
        <Card><p className="text-sm text-muted">Credits earned</p><p className="mt-1 text-2xl font-semibold text-fg">{data.credits_earned}</p></Card>
      </div>

      <SendInvite left={data.left} onSent={load} />
      <ShareLink link={data.link} code={data.code} />
      <Invitees data={data} onChange={load} />

      <p className="text-sm text-muted">
        Each invite or sign-up through your link uses one of your {data.limit} slots; revoking an invite nobody used
        gives it back. Rewards need a real, different person with a verified email. Throwaway addresses and sign-ups
        that look like the same person don&apos;t count, and some are checked by hand first.
      </p>
    </div>
  );
}

function SendInvite({ left, onSent }: { left: number; onSent: () => void }) {
  const id = useId();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSent(null);
    try {
      const res = await userApi.sendInvite(email.trim());
      setSent(`Invite sent to ${res.email}. It works until ${day(res.expires_at)}.`);
      setEmail("");
      onSent();
    } catch (err) {
      setError(userError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card as="form" onSubmit={send} className="space-y-3">
      <h2 className="font-medium text-fg">Invite by email</h2>
      <p className="text-sm text-muted">We send one email. They sign up with that address and the invite is applied; no code to type.</p>
      <div>
        <Label htmlFor={`${id}-email`}>Friend&apos;s email</Label>
        <div className="flex flex-wrap gap-2">
          <input id={`${id}-email`} type="email" required autoComplete="off" maxLength={254} className={`${inputClass} min-w-0 flex-1`}
            value={email} onChange={(e) => setEmail(e.target.value)} disabled={left === 0} placeholder="friend@example.com" />
          <Button type="submit" className="mt-1.5" busy={busy} disabled={left === 0 || !email.trim()}>Send invite</Button>
        </div>
      </div>
      {left === 0 && <p className="text-sm text-muted">You&apos;ve used all your invites. Revoke one nobody has used to free a slot.</p>}
      {error && <p role="alert" className="text-sm text-bad">{error}</p>}
      {sent && <p role="status" className="flex items-center gap-1 text-sm text-ok"><CheckIcon />{sent}</p>}
    </Card>
  );
}

function ShareLink({ link, code }: { link: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    } catch { /* clipboard blocked: the link is selectable */ }
  };
  return (
    <Card>
      <h2 className="font-medium text-fg">Your link</h2>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <code data-testid="referral-link" className="min-w-0 flex-1 truncate rounded-lg bg-surface-2 px-3 py-2 text-sm">{link}</code>
        <Button variant="secondary" onClick={() => void copy()}>{copied ? "Copied" : "Copy link"}</Button>
      </div>
      <p className="mt-2 text-sm text-muted">Your invite code is <span className="font-mono font-medium text-fg">{code}</span>.</p>
      <p role="status" className="sr-only">{copied ? "Link copied" : ""}</p>
    </Card>
  );
}

function Invitees({ data, onChange }: { data: Invites; onChange: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function revoke(id: string) {
    setBusy(id);
    setError(null);
    try { await userApi.revokeInvite(id); onChange(); } catch (e) { setError(userError(e)); } finally { setBusy(null); }
  }
  return (
    <Card>
      <h2 className="font-medium text-fg">Your invites</h2>
      {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
      {data.invitees.length === 0 ? (
        <div className="mt-3"><EmptyState title="No invites yet">Friends you invite, or who join through your link, show up here.</EmptyState></div>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-left text-sm">
            <thead className="text-xs text-muted">
              <tr><th scope="col" className="py-2 pr-3 font-medium">Friend</th><th scope="col" className="py-2 pr-3 font-medium">How</th>
                <th scope="col" className="py-2 pr-3 font-medium">Status</th><th scope="col" className="py-2 pr-3 font-medium">Since</th>
                <th scope="col" className="py-2 font-medium"><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.invitees.map((i) => {
                const s = STATUS[i.status];
                return (
                  <tr key={i.id}>
                    <td className="py-2 pr-3 text-fg">{i.email}</td>
                    <td className="py-2 pr-3 text-muted">{i.via === "email" ? "Email invite" : "Your link"}</td>
                    <td className="py-2 pr-3">
                      <span className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-0.5 text-xs font-medium ${s.cls}`}>
                        <s.Icon />{s.word}{i.status === "rewarded" && ` · +${credits(data.reward_credits)}`}
                      </span>
                      {i.status === "joined" && data.trigger === "on_first_tailoring" && (
                        <span className="ml-2 text-xs text-muted">Waiting for their first tailoring</span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-muted">{day(i.created_at)}</td>
                    <td className="py-2 text-right">
                      {i.can_revoke && (
                        <Button variant="ghost" className="min-h-9 px-3" busy={busy === i.id} aria-label={`Revoke the invite to ${i.email}`}
                          onClick={() => revoke(i.id)}>Revoke</Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
