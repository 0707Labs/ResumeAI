/**
 * Server-side session check: forwards the visitor's cookies to FastAPI's /api/me.
 * "signed_out" only on a definite 401; if the backend can't be reached we don't
 * guess (the API still refuses unauthenticated calls).
 */
import { cookies } from "next/headers";
import { cache } from "react";

import { backendUrl } from "./backend";
import * as S from "./schemas";

const BACKEND_URL = backendUrl();

export type SessionUser = S.Me | "signed_out" | "unknown";

/** The signed-in user as the backend sees them right now (role and capabilities included).
 * Asked once per request however many layouts and pages call it. */
export const currentUser = cache(async (): Promise<SessionUser> => {
  const jar = await cookies();
  const cookie = jar.getAll().map((c) => `${c.name}=${c.value}`).join("; ");
  if (!cookie) return "signed_out";
  try {
    const res = await fetch(`${BACKEND_URL}/api/me`, {
      headers: { cookie },
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (res.status === 401) return "signed_out";
    if (!res.ok) return "unknown";
    const parsed = S.Me.safeParse(await res.json());
    return parsed.success ? parsed.data : "unknown";
  } catch {
    return "unknown";
  }
});

export async function sessionState(): Promise<"signed_in" | "signed_out" | "unknown"> {
  const user = await currentUser();
  return typeof user === "string" ? user : "signed_in";
}
