/**
 * Server-side session check: forwards the visitor's cookies to FastAPI's /api/me.
 * "signed_out" only on a definite 401; if the backend can't be reached we don't
 * guess (the API still refuses unauthenticated calls).
 */
import { cookies } from "next/headers";

import * as S from "./schemas";

const BACKEND_URL = (process.env.RT_BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");

export async function sessionState(): Promise<"signed_in" | "signed_out" | "unknown"> {
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
    return S.Me.safeParse(await res.json()).success ? "signed_in" : "unknown";
  } catch {
    return "unknown";
  }
}
