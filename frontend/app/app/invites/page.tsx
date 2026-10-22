"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AuthErrorAlert } from "@/components/auth/AuthCard";
import { CheckIcon, ErrorIcon, InfoIcon } from "@/components/icons";
import { Alert, Button, Card, Spinner } from "@/components/ui";
import { AuthError } from "@/lib/auth";
import { REASON_TEXT, referralsApi } from "@/lib/referrals";
import type { Referrals } from "@/lib/schemas";

const when = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

const STATUS = {
  rewarded: { Icon: CheckIcon, word: "Rewarded", cls: "bg-ok-bg text-ok" },
  pending: { Icon: InfoIcon, word: "Pending", cls: "bg-surface-2 text-fg" },
  rejected: { Icon: ErrorIcon, word: "Not rewarded", cls: "bg-bad-bg text-bad" },
} as const;

export default function ReferralsPage() {
  const [data, setData] = useState<Referrals | null | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    referralsApi.overview().then(setData).catch((e) => {
      if (e instanceof AuthError && e.status === 401) setData(null);
      else setError(e);
    });
  }, []);

  if (error) return <div className="mx-auto max-w-2xl"><AuthErrorAlert error={error} /></div>;
  if (data === undefined) return <p role="status" className="flex items-center gap-2 text-muted"><Spinner /> Loading…</p>;
  if (data === null) {
    return (
      <Alert tone="info" title="Sign in to see your referrals">
        <Link href="/signin?next=/app/invites" className="font-medium text-accent underline">Sign in</Link> to
        get your link.
      </Alert>
    );
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(data.link);
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    } catch { /* clipboard blocked: the link is selectable */ }
  };
  const earnedWhen = data.trigger === "on_first_tailoring"
    ? "once they finish their first tailoring"
    : "as soon as their account is created";
  const credits = (n: number) => `${n} credit${n === 1 ? "" : "s"}`;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Invite friends</h1>
        <p className="mt-1 text-muted">
          Share your link. When a friend signs up with it, you get {credits(data.reward_credits)} {earnedWhen}
          {data.invitee_reward_credits > 0 && <>, and they get {credits(data.invitee_reward_credits)} to start</>}.
          Up to {data.monthly_cap} rewards a month.
        </p>
      </div>

      {!data.enabled && <Alert tone="warn" title="Referrals are paused">Links still work, but nothing is rewarded right now.</Alert>}

      <Card>
        <h2 className="text-lg font-semibold">Your link</h2>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <code data-testid="referral-link" className="min-w-0 flex-1 truncate rounded-lg bg-surface-2 px-3 py-2 text-sm">
            {data.link}
          </code>
          <Button variant="secondary" onClick={() => void copy()}>{copied ? "Copied" : "Copy link"}</Button>
        </div>
        <p className="mt-2 text-sm text-muted">
          Your code is <span className="font-mono font-medium text-fg">{data.code}</span>.
          {data.invite_only && (
            <> While sign-up is invite-only, your link also works as an invite: {data.invites_left} left.</>
          )}
        </p>
      </Card>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card><p className="text-sm text-muted">Earned</p><p className="mt-1 text-2xl font-semibold">{credits(data.total_earned)}</p></Card>
        <Card><p className="text-sm text-muted">Rewarded</p><p className="mt-1 text-2xl font-semibold">{data.rewarded}</p></Card>
        <Card><p className="text-sm text-muted">Pending</p><p className="mt-1 text-2xl font-semibold">{data.pending}</p></Card>
      </div>

      <Card>
        <h2 className="text-lg font-semibold">Friends who joined</h2>
        {data.referrals.length === 0 ? (
          <p className="mt-2 text-sm text-muted">No one yet. When a friend signs up with your link, they show up here.</p>
        ) : (
          <ul className="mt-3 divide-y divide-border">
            {data.referrals.map((r) => {
              const s = STATUS[r.status];
              const why = r.status === "pending" && !r.needs_review
                ? (data.trigger === "on_first_tailoring" ? "Waiting for their first tailoring" : null)
                : r.reason ? REASON_TEXT[r.reason] ?? null : null;
              return (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
                  <span>A friend joined on {when(r.created_at)}{why && <span className="text-muted"> · {why}</span>}</span>
                  <span className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 font-medium ${s.cls}`}>
                    <s.Icon /> {s.word}{r.status === "rewarded" && ` · +${credits(r.credits)}`}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
      <p className="text-sm text-muted">
        Rewards need a real, different person with a verified email. Throwaway addresses and sign-ups that look like
        the same person don&apos;t count, and some are checked by hand first.
      </p>
    </div>
  );
}
