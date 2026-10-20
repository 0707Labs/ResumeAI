"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AuthCard } from "@/components/auth/AuthCard";
import { EmailForm } from "@/components/auth/EmailForm";
import { PendingExpired } from "@/components/auth/PendingExpired";
import { usePending } from "@/components/auth/usePending";
import { Alert } from "@/components/ui";
import { authApi } from "@/lib/auth";

/** The provider (usually GitHub) shared no verified email: confirm one by link. */
export default function VerifyEmailPage() {
  const router = useRouter();
  const { pending, error } = usePending();
  const done = pending?.kind === "signup";
  useEffect(() => { if (done) router.replace("/signup/invite"); }, [done, router]);

  if (pending === undefined || done) return null;
  if (pending === null) return <PendingExpired error={error} />;
  return (
    <AuthCard title="Confirm your email">
      <Alert tone="warn" title="Email not verified">
        Your {pending.provider === "github" ? "GitHub" : "Google"} account didn&apos;t share a verified email address.
        We only use verified addresses, so we&apos;ll email you a link to confirm one.
      </Alert>
      <EmailForm id="verify-email" label="Your email" button="Send confirmation link"
        sentTitle="Check your email" send={authApi.pendingEmail} />
    </AuthCard>
  );
}
