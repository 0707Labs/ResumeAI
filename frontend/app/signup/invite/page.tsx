"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { AuthCard, AuthErrorAlert } from "@/components/auth/AuthCard";
import { PendingExpired } from "@/components/auth/PendingExpired";
import { usePending } from "@/components/auth/usePending";
import { Alert, Button, Label, inputClass } from "@/components/ui";
import { AuthError, authApi } from "@/lib/auth";

const PROVIDER = { google: "Google", github: "GitHub", email: "an email link" } as const;

export default function InvitePage() {
  const router = useRouter();
  const { pending, error: loadError } = usePending();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const redirect = pending?.kind === "needs_email" ? "/signup/verify-email"
    : pending?.invite_accepted ? "/signup/consent" : null;
  useEffect(() => { if (redirect) router.replace(redirect); }, [redirect, router]);

  if (pending === undefined || redirect) return null;
  if (pending === null) return <PendingExpired error={loadError} />;

  async function check(withCode?: string) {
    setBusy(true);
    setError(null);
    try {
      await authApi.checkInvite(withCode);
      router.push("/signup/consent");
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); void check(code.trim()); };
  const noInvite = error instanceof AuthError && error.code === "no_invite";

  return (
    <AuthCard title="Enter your invite"
      intro={<>Signing up as <strong className="text-fg">{pending.email}</strong> with {PROVIDER[pending.provider]}.</>}>
      {pending.has_bound_invite && (
        <Alert tone="ok" title="We found an invite for you">
          <Button className="mt-2" busy={busy} onClick={() => void check()}>Use my invite</Button>
        </Alert>
      )}
      <form onSubmit={submit} className="space-y-3">
        <div>
          <Label htmlFor="invite-code" hint="(like ABCD-EFGH-JKLM)">Invite code</Label>
          <input id="invite-code" autoComplete="off" spellCheck={false} value={code}
            onChange={(e) => setCode(e.target.value)} className={`${inputClass} font-mono uppercase`} />
        </div>
        <AuthErrorAlert error={error}>
          {noInvite && <Link href="/waitlist" className="font-medium underline">Join the waitlist</Link>}
        </AuthErrorAlert>
        <Button type="submit" className="w-full" busy={busy} disabled={!code.trim()}>Continue</Button>
      </form>
      <p className="text-sm text-muted">
        Don&apos;t have an invite? <Link href="/waitlist" className="font-medium text-accent underline">Join the waitlist</Link> and
        we&apos;ll email you when there&apos;s a spot.
      </p>
    </AuthCard>
  );
}
