"use client";

import { type FormEvent, useEffect, useState } from "react";

import { AuthCard, AuthErrorAlert } from "@/components/auth/AuthCard";
import { Alert, Button, Label, inputClass } from "@/components/ui";
import { authApi } from "@/lib/auth";

/** Pre-filled from the sign-in in progress (never from the URL). */
export default function WaitlistPage() {
  const [email, setEmail] = useState("");
  const [noticeId, setNoticeId] = useState<string | null | undefined>(undefined);
  const [adult, setAdult] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [joined, setJoined] = useState(false);

  useEffect(() => {
    authApi.pending().then((p) => { if (p?.email) setEmail((e) => e || p.email!); }).catch(() => {});
    authApi.notices()
      .then((list) => setNoticeId(list.find((n) => n.purpose === "waitlist")?.id ?? null))
      .catch(() => setNoticeId(null));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!noticeId) return;
    setBusy(true);
    setError(null);
    try {
      await authApi.joinWaitlist(email.trim(), noticeId);
      setJoined(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (joined) {
    return (
      <AuthCard title="You're on the list">
        <Alert tone="ok" title="Thanks for waiting" role="status">
          We&apos;ll email <strong>{email.trim()}</strong> when there&apos;s a spot for you.
        </Alert>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Join the waitlist" intro="Resume Tailor is invite-only for now. Leave your email and we'll invite you.">
      {noticeId === null && <Alert tone="warn" title="The waitlist isn't open yet">Please check back soon.</Alert>}
      <form onSubmit={submit} className="space-y-3">
        <div>
          <Label htmlFor="waitlist-email">Email</Label>
          <input id="waitlist-email" type="email" autoComplete="email" value={email}
            onChange={(e) => setEmail(e.target.value)} className={inputClass} />
        </div>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-0.5" checked={adult} onChange={(e) => setAdult(e.target.checked)} />
          <span>I confirm I am 18 years of age or older.</span>
        </label>
        <p className="text-xs text-muted">
          We keep your email only to invite you, and you can ask us to remove it any time.
        </p>
        <AuthErrorAlert error={error} />
        <Button type="submit" className="w-full" busy={busy} disabled={!email.includes("@") || !adult || !noticeId}>
          Join the waitlist
        </Button>
      </form>
    </AuthCard>
  );
}
