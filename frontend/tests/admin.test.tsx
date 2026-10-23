import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AdminShell } from "@/components/admin/AdminShell";
import { useSignedInRedirect } from "@/components/auth/useSignedInRedirect";
import { classify } from "@/lib/api";
import { can, isStaff, reauthUrl, sectionsFor } from "@/lib/roles";
import { Me } from "@/lib/schemas";
import { isProtected } from "@/lib/workspace";

const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/admin/billing",
  useSearchParams: () => new URLSearchParams(),
}));

const base = { id: "0b6f1d9e-2c4a-4f7b-9d1e-3a5c7e9f1b2d", email: "staff@example.com", name: null, status: "active", onboarded: true, avatar_url: null } as const;
const SUPPORT = Me.parse({ ...base, role: "support", capabilities: ["staff.access", "tickets.read", "tickets.write", "users.read"], onboarded: true, avatar_url: null });
const ADMIN = Me.parse({ ...base, role: "admin",
  capabilities: ["staff.access", "users.read", "audit.read", "billing.read", "billing.write", "referrals.decide"], onboarded: true, avatar_url: null });
const USER = Me.parse({ ...base, role: "user", capabilities: [], onboarded: true, avatar_url: null });

describe("roles", () => {
  it("reads capabilities from /api/me, never the role name", () => {
    expect(can(ADMIN, "billing.read")).toBe(true);
    expect(can(SUPPORT, "billing.read")).toBe(false);
    const promotedInTheClient: Me = { ...USER, role: "superadmin" };
    expect(can(promotedInTheClient, "staff.access")).toBe(false);  // a role name without capabilities is nothing
    expect(isStaff(SUPPORT) && isStaff(ADMIN) && !isStaff(USER) && !isStaff(null)).toBe(true);
  });

  it("shows each role only the sections it can open", () => {
    expect(sectionsFor(SUPPORT).map((s) => s.href)).toEqual(["/admin", "/admin/users", "/admin/support"]);
    expect(sectionsFor(ADMIN).map((s) => s.href)).toEqual(["/admin", "/admin/users", "/admin/referrals", "/admin/revenue", "/admin/billing", "/admin/settings"]);
    expect(sectionsFor(USER)).toEqual([]);
  });

  it("accepts roles and capabilities the backend may add later", () => {
    expect(Me.safeParse({ ...base, role: "superadmin", capabilities: ["staff.access", "something.new"], onboarded: true, avatar_url: null }).success).toBe(true);
    expect(Me.safeParse({ ...base, role: "owner", capabilities: [], onboarded: true, avatar_url: null }).success).toBe(false);
    expect(Me.safeParse({ ...base, role: "user" }).success).toBe(false);  // capabilities are required
  });
});

describe("admin protection", () => {
  it("guards /admin like the workspace", () => {
    expect(isProtected("/admin")).toBe(true);
    expect(isProtected("/admin/billing")).toBe(true);
    expect(isProtected("/adminx")).toBe(false);
  });

  it("tells step-up and forbidden apart from other errors", () => {
    expect(classify(401, "reauth_required")).toBe("reauth_required");
    expect(classify(403, "forbidden")).toBe("forbidden");
    expect(classify(503, "analyses_paused")).toBe("analyses_paused");  // budget kill switch or a manual pause
    expect(classify(503)).toBe("server");
    expect(classify(401, "not_signed_in")).toBe("invalid_input");
    expect(reauthUrl("/admin/settings")).toBe("/signin?next=%2Fadmin%2Fsettings&reauth=1");
  });

  it("lets a signed-in staff member reach the sign-in page to re-authenticate", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ...base, role: "admin", capabilities: [], onboarded: true, avatar_url: null })));
    vi.stubGlobal("fetch", fetchMock);
    function Probe({ skip }: { skip: boolean }) { useSignedInRedirect("/admin", { skip }); return null; }
    render(<Probe skip />);
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

describe("AdminShell", () => {
  it("lists only the role's sections and marks the current one", () => {
    render(<AdminShell me={ADMIN} initialTheme="system"><p>content</p></AdminShell>);
    const [mobile, desktop] = screen.getAllByRole("navigation", { name: "Admin sections" });
    for (const nav of [mobile, desktop]) {
      expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual(["Overview", "Users", "Referrals", "Revenue", "Billing", "Settings"]);
      expect(within(nav).getByRole("link", { name: "Billing" })).toHaveAttribute("aria-current", "page");
      expect(within(nav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    }
    expect(screen.getByText(/staff@example.com/)).toHaveTextContent("staff@example.com · Admin");
    expect(screen.getByText("content")).toBeInTheDocument();
  });

  it("gives support no billing or referral links", () => {
    render(<AdminShell me={SUPPORT} initialTheme="system"><p>content</p></AdminShell>);
    expect(screen.queryByRole("link", { name: "Billing" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Referrals" })).toBeNull();
  });
});
