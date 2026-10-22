/**
 * What the signed-in staff member may see in /admin. Mirrors app/auth/roles.py only for
 * display: the capabilities come from /api/me, and the API checks again on every call.
 */
import type { Me } from "./schemas";

export type Capability =
  | "staff.access" | "users.read" | "tickets.read" | "tickets.write" | "audit.read" | "users.write"
  | "credits.adjust" | "passes.grant" | "invites.write" | "referrals.decide" | "billing.read"
  | "billing.write" | "costs.read" | "quality.read" | "integrations.read" | "users.delete"
  | "roles.write" | "settings.write" | "secrets.hint";

export function can(me: Pick<Me, "capabilities"> | null | undefined, capability: Capability): boolean {
  return !!me && me.capabilities.includes(capability);
}

export const isStaff = (me: Pick<Me, "capabilities"> | null | undefined) => can(me, "staff.access");

export const ROLE_LABEL: Record<Me["role"], string> = {
  user: "User",
  support: "Support",
  admin: "Admin",
  superadmin: "Superadmin",
};

export interface AdminSection {
  href: string;
  label: string;
  needs: Capability;
  description: string;
}

/** Admin sections in sidebar order. Later steps add users, invites, costs and the rest. */
export const ADMIN_SECTIONS: AdminSection[] = [
  { href: "/admin", label: "Overview", needs: "staff.access", description: "Where things stand." },
  { href: "/admin/billing", label: "Billing", needs: "billing.read",
    description: "Revenue, LLM cost, margin, billing reviews and webhook failures." },
  { href: "/admin/referrals", label: "Referrals", needs: "referrals.decide",
    description: "Flagged referrals to approve or reject, and paid ones to reverse." },
];

export const sectionsFor = (me: Pick<Me, "capabilities">) => ADMIN_SECTIONS.filter((s) => can(me, s.needs));

/** Where to send someone whose superadmin action needs a fresh sign-in (401 reauth_required). */
export function reauthUrl(path: string): string {
  return `/signin?next=${encodeURIComponent(path)}&reauth=1`;
}
