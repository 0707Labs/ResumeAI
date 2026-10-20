"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { AuthCard, AuthErrorAlert } from "@/components/auth/AuthCard";
import { Spinner } from "@/components/ui";
import { AuthError, NEXT_PAGE, authApi } from "@/lib/auth";

/** Where an emailed link lands. The token is in the #fragment, so it never reaches
 * a server log; we read it, wipe it from the address bar, and post it once. */
export default function EmailLinkPage() {
  const router = useRouter();
  const [error, setError] = useState<unknown>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return; // StrictMode runs effects twice; the token is single-use
    started.current = true;
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    window.history.replaceState(null, "", window.location.pathname);
    if (!token) {
      setError(new AuthError("link_invalid", 400));
      return;
    }
    authApi.verifyEmail(token).then((step) => router.replace(NEXT_PAGE[step.next])).catch(setError);
  }, [router]);

  return (
    <AuthCard title={error ? "That didn't work" : "Signing you in"}>
      {error ? (
        <>
          <AuthErrorAlert error={error} />
          <Link href="/login" className="text-sm font-medium text-accent underline">Back to sign in</Link>
        </>
      ) : (
        <p className="flex items-center gap-2 text-sm text-muted"><Spinner label="Checking your link" /> Checking your link…</p>
      )}
    </AuthCard>
  );
}
