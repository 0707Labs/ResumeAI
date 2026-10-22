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

/** Admin sections in sidebar order. */
export const ADMIN_SECTIONS: AdminSection[] = [
  { href: "/admin", label: "Overview", needs: "staff.access",
    description: "Users, activity, revenue and Claude cost, and the sign-up funnel." },
  { href: "/admin/users", label: "Users", needs: "users.read",
    description: "Find an account, see its history (metadata only), and act on it." },
  { href: "/admin/invites", label: "Invites", needs: "invites.write",
    description: "Generate invite codes, work the waitlist, invite settings and the funnel." },
  { href: "/admin/referrals", label: "Referrals", needs: "referrals.decide",
    description: "Flagged referrals to approve or reject, paid ones to reverse, and the rules." },
  { href: "/admin/support", label: "Support", needs: "tickets.read",
    description: "Messages from the contact form: reply, note, assign, close." },
  { href: "/admin/revenue", label: "Revenue", needs: "billing.read",
    description: "Gross, refunds, fees and net by product and currency; subscriptions; payments and refunds." },
  { href: "/admin/costs", label: "Costs", needs: "costs.read",
    description: "Claude spend by step, model and plan; budgets, the kill switch and margin." },
  { href: "/admin/billing", label: "Billing", needs: "billing.read",
    description: "Billing reviews, webhook failures and the credit ledger." },
  { href: "/admin/quality", label: "Quality", needs: "quality.read",
    description: "Verifier flags and overrides, parse failures, ATS lift, and fabrication reports." },
  { href: "/admin/integrations", label: "Integrations", needs: "integrations.read",
    description: "Claude, the database, Dodo, email and sign-in providers: status, health checks, webhooks, models." },
  { href: "/admin/settings", label: "Settings", needs: "audit.read",
    description: "Feature flags, plans and pricing, legal versions, staff roles, and the audit log." },
];

export const sectionsFor = (me: Pick<Me, "capabilities">) => ADMIN_SECTIONS.filter((s) => can(me, s.needs));

/** Where to send someone whose superadmin action needs a fresh sign-in (401 reauth_required). */
export function reauthUrl(path: string): string {
  return `/signin?next=${encodeURIComponent(path)}&reauth=1`;
}
