"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AuthCard, AuthErrorAlert } from "@/components/auth/AuthCard";
import { SignInOptions } from "@/components/auth/SignInOptions";
import { useInviteOnly } from "@/components/auth/useInviteOnly";
import { useSignedInRedirect } from "@/components/auth/useSignedInRedirect";
import { safeNext } from "@/lib/auth";

export default function SignInPage() {
  return (
    <Suspense fallback={null}>
      <SignIn />
    </Suspense>
  );
}

function SignIn() {
  const params = useSearchParams();
  const next = params.get("next") ?? undefined;
  const inviteOnly = useInviteOnly();
  useSignedInRedirect(safeNext(next));
  return (
    <AuthCard title="Sign in" intro="Welcome back. Pick the way you signed up, or get a link by email.">
      <AuthErrorAlert error={params.get("error")} />
      <SignInOptions next={next} />
      <p className="text-sm text-muted">
        New here? <Link href="/signup" className="font-medium text-accent underline">Create an account</Link>.
        {inviteOnly && " You'll need an invite."}
      </p>
    </AuthCard>
  );
}
