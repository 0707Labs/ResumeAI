/**
 * Server-side reads for the public pages (landing, legal). They render on the
 * server, so they call FastAPI directly (RT_BACKEND_URL, as next.config.ts does)
 * and fall back to safe defaults when it's unreachable: invite-only on, no prices.
 */
import type { z } from "zod";

import * as S from "./schemas";

const BACKEND_URL = (process.env.RT_BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
const REVALIDATE_S = 60;

async function fetchPublic<T extends z.ZodType>(schema: T, path: string): Promise<z.infer<T> | null> {
  try {
    const res = await fetch(`${BACKEND_URL}${path}`, {
      next: { revalidate: REVALIDATE_S },
      signal: AbortSignal.timeout(2000),
    });
    if (!res.ok) return null;
    const parsed = schema.safeParse(await res.json());
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

/** Invite-only unless the backend says otherwise (RT_INVITE_ONLY). */
export async function getPublicConfig(): Promise<S.PublicConfig> {
  return (await fetchPublic(S.PublicConfig, "/api/auth/config")) ?? { invite_only: true };
}

/** What we sell (billing.toml via /api/billing/plans), or null if it can't be read. */
export function getPlans(): Promise<S.Plans | null> {
  return fetchPublic(S.Plans, "/api/billing/plans");
}

/** Where people reach the company: footer, legal pages. Empty until configured. */
export const COMPANY = {
  product: "Resume Tailor",
  lab: "0707Labs",
  legalName: "MealOBox Foodtech Pvt Ltd",
  supportEmail: process.env.NEXT_PUBLIC_SUPPORT_EMAIL ?? "",
  grievanceName: process.env.NEXT_PUBLIC_GRIEVANCE_OFFICER_NAME ?? "",
  grievanceEmail: process.env.NEXT_PUBLIC_GRIEVANCE_OFFICER_EMAIL ?? "",
} as const;

/** Absolute site URL for canonical links, Open Graph and the sitemap. */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/$/, "");
