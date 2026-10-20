"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { AuthCard, AuthErrorAlert } from "@/components/auth/AuthCard";
import { PendingExpired } from "@/components/auth/PendingExpired";
import { usePending } from "@/components/auth/usePending";
import { Alert, Button } from "@/components/ui";
import { AuthError, authApi } from "@/lib/auth";
import type { Notice } from "@/lib/schemas";

type Current = Partial<Record<Notice["purpose"], Notice>>;

/** Required before any account exists: 18+ and Terms + Privacy. Research is optional and off. */
export default function ConsentPage() {
  const router = useRouter();
  const { pending, error: loadError } = usePending();
  const [notices, setNotices] = useState<Current | null>(null);
  const [adult, setAdult] = useState(false);
  const [terms, setTerms] = useState(false);
  const [research, setResearch] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const loadNotices = () =>
    authApi.notices().then((list) => setNotices(Object.fromEntries(list.map((n) => [n.purpose, n])))).catch(setError);
  useEffect(() => { void loadNotices(); }, []);

  const needsInvite = pending && !pending.invite_accepted;
  useEffect(() => { if (needsInvite) router.replace("/signup/invite"); }, [needsInvite, router]);

  if (pending === undefined || needsInvite) return null;
  if (pending === null) return <PendingExpired error={loadError} />;
  if (notices && (!notices.service || !notices.age_18_plus)) {
    return (
      <AuthCard title="Almost there">
        <Alert tone="warn" title="Sign-up isn't open yet">Our terms aren&apos;t published yet. Please try again soon.</Alert>
      </AuthCard>
    );
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!notices?.service || !notices.age_18_plus || !adult || !terms) return;
    setBusy(true);
    setError(null);
    try {
      await authApi.completeSignup({
        age_18_plus: true,
        accept_terms: true,
        research_opt_in: research && !!notices.research,
        notice_ids: {
          service: notices.service.id,
          age_18_plus: notices.age_18_plus.id,
          ...(research && notices.research ? { research: notices.research.id } : {}),
        },
      });
      router.replace("/");
    } catch (err) {
      setError(err);
      setBusy(false);
      if (err instanceof AuthError && err.code === "stale_notice") void loadNotices();
    }
  }

  const backToInvite = error instanceof AuthError && error.code === "invite_unavailable";
  return (
    <AuthCard title="Before we create your account" intro="Two things are required. The last one is up to you.">
      <form onSubmit={submit} className="space-y-4">
        <fieldset className="space-y-3">
          <legend className="text-sm font-medium">Required</legend>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5" checked={adult} onChange={(e) => setAdult(e.target.checked)} />
            <span>I confirm I am 18 years of age or older.</span>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
            <span>
              I agree to the{" "}
              <a href={notices?.service?.body_url ?? "#"} target="_blank" rel="noreferrer" className="font-medium text-accent underline">
                Terms of Service and Privacy Policy
              </a>
              {notices?.service && <span className="text-muted"> (version {notices.service.version})</span>}.
            </span>
          </label>
        </fieldset>
        {notices?.research && (
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Optional</legend>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5" checked={research} onChange={(e) => setResearch(e.target.checked)} />
              <span>
                Help improve the product: you may use anonymized data from my sessions.{" "}
                <span className="text-muted">You can change this any time in your account.</span>
              </span>
            </label>
          </fieldset>
        )}
        <AuthErrorAlert error={error}>
          {backToInvite && <Link href="/signup/invite" className="font-medium underline">Enter another invite</Link>}
        </AuthErrorAlert>
        <Button type="submit" className="w-full" busy={busy} disabled={!adult || !terms || !notices}>
          Create my account
        </Button>
      </form>
    </AuthCard>
  );
}
