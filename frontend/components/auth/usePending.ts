"use client";

import { useEffect, useState } from "react";

import { authApi } from "@/lib/auth";
import type { PendingSignIn } from "@/lib/schemas";

/** The sign-in in progress: undefined while loading, null when there is none. */
export function usePending(): { pending: PendingSignIn | null | undefined; error: unknown } {
  const [pending, setPending] = useState<PendingSignIn | null | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    authApi.pending().then(setPending).catch((e) => { setError(e); setPending(null); });
  }, []);
  return { pending, error };
}
