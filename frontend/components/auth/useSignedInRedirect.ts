"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { api } from "@/lib/api";

/** Already signed in? Skip the sign-in screens and go where they were headed. */
export function useSignedInRedirect(to: string, { skip = false }: { skip?: boolean } = {}) {
  const router = useRouter();
  useEffect(() => {
    if (skip) return;
    let live = true;
    api.me().then((me) => { if (live && me) router.replace(to); }).catch(() => {});
    return () => { live = false; };
  }, [router, to, skip]);
}
