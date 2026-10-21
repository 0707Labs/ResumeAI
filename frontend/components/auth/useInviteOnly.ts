"use client";

import { useEffect, useState } from "react";

import { authApi } from "@/lib/auth";

/** Whether signup needs an invite (RT_INVITE_ONLY). Assumed true until the backend says otherwise. */
export function useInviteOnly(): boolean {
  const [inviteOnly, setInviteOnly] = useState(true);
  useEffect(() => {
    let live = true;
    void authApi.config().then((c) => { if (live) setInviteOnly(c.invite_only); });
    return () => { live = false; };
  }, []);
  return inviteOnly;
}
