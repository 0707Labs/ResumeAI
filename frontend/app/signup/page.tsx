"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AuthCard, AuthErrorAlert } from "@/components/auth/AuthCard";
import { SignInOptions } from "@/components/auth/SignInOptions";

export default function SignupPage() {
  return (
    <Suspense fallback={null}>
      <Signup />
    </Suspense>
  );
}

function Signup() {
  const params = useSearchParams();
  return (
    <AuthCard
      title="Create your account"
      intro={
        <ol className="list-decimal space-y-0.5 pl-5">
          <li>Continue with Google, GitHub or an email link.</li>
          <li>Enter your invite code.</li>
          <li>Confirm you&apos;re 18 or older and agree to the terms.</li>
        </ol>
      }
    >
      <AuthErrorAlert error={params.get("error")} />
      <SignInOptions />
      <p className="text-sm text-muted">
        No invite yet? <Link href="/waitlist" className="font-medium text-accent underline">Join the waitlist</Link>.
        Already have an account? <Link href="/login" className="font-medium text-accent underline">Sign in</Link>.
      </p>
    </AuthCard>
  );
}
