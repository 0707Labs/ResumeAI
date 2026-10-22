import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminInvitesPage from "@/app/admin/invites/page";
import AdminTicketPage from "@/app/admin/support/[id]/page";
import AdminUserPage from "@/app/admin/users/[id]/page";
import AdminUsersPage from "@/app/admin/users/page";
import { ReasonDialog } from "@/components/admin/ui";
import { adminError } from "@/lib/adminApi";
import { AuthError } from "@/lib/auth";

const router = { push: vi.fn(), replace: vi.fn() };
let search = new URLSearchParams();
let params: Record<string, string> = {};
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/admin/users",
  useSearchParams: () => search,
  useParams: () => params,
}));

type Handler = (init?: RequestInit) => Response;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function routes(table: Record<string, Handler | unknown>) {
  const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(url)}`;
    if (!(key in table)) throw new Error(`unrouted ${key}`);
    const entry = table[key];
    return typeof entry === "function" ? (entry as Handler)(init) : json(entry);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const bodyOf = (fetchMock: ReturnType<typeof routes>, key: string) => {
  const call = fetchMock.mock.calls.filter(([u, i]) => `${i?.method ?? "GET"} ${String(u)}` === key).at(-1);
  return call ? JSON.parse(String(call[1]?.body)) : undefined;
};

const U1 = "11111111-1111-4111-8111-111111111111";
const T1 = "22222222-2222-4222-8222-222222222222";
const W1 = "33333333-3333-4333-8333-333333333333";
const B1 = "44444444-4444-4444-8444-444444444444";
const AT = "2026-10-20T10:00:00Z";
const ROW = { id: U1, name: "Ada", email: "ada@example.com", role: "user", status: "active", plan: "free", credits: 2,
  created_at: AT, last_active_at: AT, tailorings: 3, downloads: 1, referrals: 0, llm_cost_usd: 0.1234 };
const DETAIL = {
  user: ROW, phone: null, onboarded: true, providers: [{ provider: "google", email: "ada@example.com", linked_at: AT }],
  plan: { kind: "credits", credits: 2, pass_days_left: null, free_left: 1, free_allowance: 2 }, ledger: [], payments: [],
  tailorings: [{ id: T1, created_at: AT, job_title: "Analyst", company: "Acme", ats_before: 61, ats_after: 77, status: "tailored",
    llm_tailored: false, purged: false, deleted: false, llm_cost_usd: 0 }],
  downloads: [], invites_sent: [], invited_with: null, referrals: [], referred_by: null, tickets: [], audit: [],
  can: { users_write: true, credits_adjust: true, passes_grant: true, users_delete: false },
};
const CSRF = { "GET /api/auth/csrf": { csrf_token: "tok" } };

beforeEach(() => { search = new URLSearchParams(); params = {}; router.replace.mockReset(); document.cookie = "rt_csrf=tok; path=/"; });
afterEach(() => vi.unstubAllGlobals());

describe("reason dialog", () => {
  it("needs a reason before confirming, and shows the server's refusal", async () => {
    const onConfirm = vi.fn(async () => { throw new Error("That would take the balance below zero."); });
    render(<ReasonDialog title="Adjust credits" confirm="Apply" onConfirm={onConfirm} onClose={vi.fn()} />);
    const apply = screen.getByRole("button", { name: "Apply" });
    expect(screen.getByRole("dialog", { name: "Adjust credits" })).toBeInTheDocument();
    expect(apply).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Reason/), "ok");
    expect(apply).toBeDisabled();  // 3 characters at least
    await userEvent.type(screen.getByLabelText(/Reason/), "!");
    await userEvent.click(apply);
    expect(await screen.findByRole("alert")).toHaveTextContent("below zero");
    expect(onConfirm).toHaveBeenCalledWith("ok!");
  });

  it("sends a step-up refusal to sign in again", () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, pathname: "/admin/invites" });
    adminError(new AuthError("reauth_required", 401), "/admin/invites");
    expect(assign).toHaveBeenCalledWith("/signin?next=%2Fadmin%2Finvites&reauth=1");
  });
});

describe("users", () => {
  it("lists users from the URL's filters and sorts by a column", async () => {
    search = new URLSearchParams("status=active&page=2");
    const fetchMock = routes({ "GET /api/admin/users?status=active&sort=created_at&direction=desc&page=2&page_size=25":
      { items: [ROW], total: 26, page: 2, page_size: 25 } });
    render(<AdminUsersPage />);
    expect(await screen.findByRole("link", { name: /ada@example.com/ })).toHaveAttribute("href", `/admin/users/${U1}`);
    expect(screen.getByText("26–26 of 26")).toBeInTheDocument();
    expect(screen.getByText("$0.12")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Credits/ }));
    expect(router.replace).toHaveBeenCalledWith("/admin/users?status=active&sort=credits_balance&direction=desc", { scroll: false });
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute("href", "/api/admin/users/export.csv?status=active&sort=created_at&direction=desc");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("adjusts credits with a reason", async () => {
    params = { id: U1 };
    const fetchMock = routes({ ...CSRF, [`GET /api/admin/users/${U1}`]: DETAIL,
      [`POST /api/admin/users/${U1}/credits`]: { credits_balance: 7 } });
    render(<AdminUserPage />);
    expect(await screen.findByText("Analyst at Acme")).toBeInTheDocument();
    expect(screen.getByText("61 → 77")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Adjust credits" }));
    await userEvent.type(screen.getByLabelText(/Credits/), "5");
    await userEvent.type(screen.getByLabelText(/Reason/), "goodwill");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Credits added: 5.");
    expect(bodyOf(fetchMock, `POST /api/admin/users/${U1}/credits`)).toEqual({ delta: 5, reason: "goodwill" });
  });

  it("offers no actions to a role that can't take them", async () => {
    params = { id: U1 };
    routes({ [`GET /api/admin/users/${U1}`]: { ...DETAIL, plan: null, ledger: null, payments: null,
      can: { users_write: false, credits_adjust: false, passes_grant: false, users_delete: false } } });
    render(<AdminUserPage />);
    expect(await screen.findByText("Billing details need an admin.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Actions" })).toBeNull();
    expect(screen.queryByRole("table", { name: "Credit ledger" })).toBeNull();
  });
});

describe("invites", () => {
  const PAGE = { items: [], total: 0, page: 1, page_size: 25 };

  it("generates codes and shows them once", async () => {
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
    const fetchMock = routes({ ...CSRF, "GET /api/me": { id: U1, email: "a@x.com", name: null, role: "admin", status: "active",
      capabilities: ["staff.access", "invites.write"], onboarded: true, avatar_url: null },
      "GET /api/admin/invites?page=1&page_size=25": PAGE,
      "POST /api/admin/invites": () => json({ batch_id: B1, codes: ["ABCD-EFGH-JKLM", "NPQR-STUV-WXYZ"], expires_at: null }, 201) });
    render(<AdminInvitesPage />);
    await userEvent.clear(await screen.findByLabelText(/How many/));
    await userEvent.type(screen.getByLabelText(/How many/), "2");
    await userEvent.type(screen.getByLabelText(/Campaign/), "launch");
    await userEvent.click(screen.getByRole("button", { name: "Generate" }));
    expect(await screen.findByLabelText("New codes")).toHaveValue("ABCD-EFGH-JKLM\nNPQR-STUV-WXYZ");
    expect(screen.getByText(/can.t be shown again/)).toBeInTheDocument();
    expect(bodyOf(fetchMock, "POST /api/admin/invites")).toEqual({ count: 2, max_uses: 1, campaign: "launch" });
  });

  it("approves selected waitlist entries", async () => {
    search = new URLSearchParams("tab=waitlist");
    const WAIT = { items: [{ id: W1, email: "w@example.org", source: "landing", status: "waiting", created_at: AT, invited_at: null }],
      total: 1, page: 1, page_size: 50 };
    const fetchMock = routes({ ...CSRF, "GET /api/me": null, "GET /api/admin/waitlist?status=waiting&page=1": WAIT,
      "POST /api/admin/waitlist/approve": { approved: 1, skipped: 0, failed: 0 } });
    render(<AdminInvitesPage />);
    await userEvent.click(await screen.findByRole("checkbox", { name: "Select w@example.org" }));
    await userEvent.click(screen.getByRole("button", { name: "Approve and email (1)" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Invited 1.");
    expect(bodyOf(fetchMock, "POST /api/admin/waitlist/approve")).toEqual({ ids: [W1] });
  });
});

describe("support ticket", () => {
  it("replies by email and keeps notes internal", async () => {
    params = { id: T1 };
    let messages: unknown[] = [];
    const ticket = () => json({ id: T1, user_id: U1, email: "ada@example.com", category: "billing", subject: "Double charge",
      status: "open", assignee_id: null, assignee_email: null, analysis_id: null, created_at: AT, updated_at: AT,
      body: "I was charged twice.", messages, staff: [] });
    const fetchMock = routes({ ...CSRF, [`GET /api/admin/support/${T1}`]: ticket,
      [`POST /api/admin/support/${T1}/reply`]: (init?: RequestInit) => {
        messages = [{ id: W1, kind: "reply", body: JSON.parse(String(init?.body)).body, author_email: "s@x.com",
          emailed_at: AT, created_at: AT }];
        return json(messages[0], 201);
      } });
    render(<AdminTicketPage />);
    expect(await screen.findByText("I was charged twice.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ada@example.com" })).toHaveAttribute("href", `/admin/users/${U1}`);
    await userEvent.type(screen.getByLabelText(/^Reply/), "Refunded.");
    await userEvent.click(screen.getByRole("button", { name: "Send reply" }));
    const thread = await screen.findByRole("list", { name: "Conversation" });
    await waitFor(() => expect(within(thread).getByText("Refunded.")).toBeInTheDocument());
    expect(within(thread).getByText(/Reply, emailed/)).toBeInTheDocument();
    expect(bodyOf(fetchMock, `POST /api/admin/support/${T1}/reply`)).toEqual({ body: "Refunded." });
  });
});
