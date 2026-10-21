"use client";

import { useEffect, useState } from "react";

import { authApi, rememberNext } from "@/lib/auth";
import type { ProviderAvailability } from "@/lib/schemas";

import { EmailForm } from "./EmailForm";
import { ProviderButtons } from "./ProviderButtons";

/** Google, GitHub, then an email link. Shared by /signin and /signup. */
export function SignInOptions({ next }: { next?: string }) {
  const [available, setAvailable] = useState<ProviderAvailability | null>(null);
  useEffect(() => {
    authApi.providers().then(setAvailable).catch(() => setAvailable({ google: false, github: false, email: true }));
  }, []);
  return (
    <>
      <ProviderButtons available={available} next={next} />
      <div className="flex items-center gap-3 text-xs text-muted" aria-hidden="true">
        <span className="h-px flex-1 bg-border" />or<span className="h-px flex-1 bg-border" />
      </div>
      <EmailForm id="signin-email" label="Email" button="Email me a sign-in link" 
        send={(email) => { rememberNext(next); return authApi.startEmail(email); }} />
    </>
  );
}
