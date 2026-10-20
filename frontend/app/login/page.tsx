"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AuthCard, AuthErrorAlert } from "@/components/auth/AuthCard";
import { SignInOptions } from "@/components/auth/SignInOptions";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <Login />
    </Suspense>
  );
}

function Login() {
  const params = useSearchParams();
  return (
    <AuthCard title="Sign in" intro="Welcome back. Pick the way you signed up, or get a link by email.">
      <AuthErrorAlert error={params.get("error")} />
      <SignInOptions next={params.get("next") ?? undefined} />
      <p className="text-sm text-muted">
        New here? <Link href="/signup" className="font-medium text-accent underline">Create an account</Link>.
        You&apos;ll need an invite.
      </p>
    </AuthCard>
  );
}
