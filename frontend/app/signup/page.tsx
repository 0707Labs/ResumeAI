"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AuthCard, AuthErrorAlert } from "@/components/auth/AuthCard";
import { SignInOptions } from "@/components/auth/SignInOptions";
import { useInviteOnly } from "@/components/auth/useInviteOnly";
import { useSignedInRedirect } from "@/components/auth/useSignedInRedirect";
import { DEFAULT_NEXT } from "@/lib/auth";

export default function SignupPage() {
  return (
    <Suspense fallback={null}>
      <Signup />
    </Suspense>
  );
}

function Signup() {
  const params = useSearchParams();
  const inviteOnly = useInviteOnly();
  useSignedInRedirect(DEFAULT_NEXT);
  return (
    <AuthCard
      title="Create your account"
      intro={
        <ol className="list-decimal space-y-0.5 pl-5">
          <li>Continue with Google, GitHub or an email link.</li>
          {inviteOnly && <li>Enter your invite code.</li>}
          <li>
            Confirm you&apos;re 18 or older and agree to the{" "}
            <Link href="/legal/terms" className="underline">Terms</Link> and{" "}
            <Link href="/legal/privacy" className="underline">Privacy Policy</Link>.
          </li>
        </ol>
      }
    >
      <AuthErrorAlert error={params.get("error")} />
      <SignInOptions />
      <p className="text-sm text-muted">
        {inviteOnly && (
          <>No invite yet? <Link href="/waitlist" className="font-medium text-accent underline">Join the waitlist</Link>. </>
        )}
        Already have an account? <Link href="/signin" className="font-medium text-accent underline">Sign in</Link>.
      </p>
    </AuthCard>
  );
}
