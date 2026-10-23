import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DownloadsPage from "@/app/app/downloads/page";
import InvitesPage from "@/app/app/invites/page";
import SupportPage from "@/app/app/support/page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/app/invites",
  useSearchParams: () => new URLSearchParams(),
}));
const openDownload = vi.fn();
vi.mock("@/lib/download", () => ({ openDownload: (url: string) => openDownload(url) }));

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

const I1 = "11111111-1111-4111-8111-111111111111";
const I2 = "22222222-2222-4222-8222-222222222222";
const D1 = "33333333-3333-4333-8333-333333333333";
const A1 = "44444444-4444-4444-8444-444444444444";
const AT = "2026-10-20T10:00:00Z";
const CSRF = { "GET /api/auth/csrf": { csrf_token: "tok" } };
const INVITES = {
  limit: 10, used: 2, left: 8, enabled: true, code: "ABCDEFGH", link: "http://localhost:3000/?ref=ABCDEFGH",
  trigger: "on_first_tailoring", reward_credits: 1, credits_earned: 1,
  invitees: [
    { id: I1, via: "email", email: "f***@example.org", status: "sent", created_at: AT, expires_at: AT, can_revoke: true },
    { id: I2, via: "link", email: "b***@example.com", status: "rewarded", created_at: AT, expires_at: null, can_revoke: false },
  ],
};

beforeEach(() => { document.cookie = "rt_csrf=tok; path=/"; openDownload.mockReset(); });
afterEach(() => vi.unstubAllGlobals());

describe("invites", () => {
  it("shows the quota, the link and each friend's status", async () => {
    routes({ "GET /api/invites": INVITES });
    render(<InvitesPage />);
    expect(await screen.findByTestId("referral-link")).toHaveTextContent("?ref=ABCDEFGH");
    expect(screen.getByRole("progressbar", { name: "Invites used" })).toHaveAttribute("aria-valuenow", "2");
    expect(screen.getByText("8")).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("Invite sent")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/Rewarded · \+1 credit/)).toBeInTheDocument();
    expect(within(rows[1]).queryByRole("button")).toBeNull();
    expect(screen.queryByText(/@example\.org/)).toHaveTextContent("f***@example.org");
  });

  it("sends an invite and refreshes", async () => {
    const fetchMock = routes({ ...CSRF, "GET /api/invites": INVITES,
      "POST /api/invites": () => json({ id: I1, email: "n***@example.org", expires_at: "2026-11-21T00:00:00Z", left: 7 }, 201) });
    render(<InvitesPage />);
    await userEvent.type(await screen.findByLabelText("Friend's email"), "new@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));
    expect(await screen.findByText(/Invite sent to n\*\*\*@example.org/)).toBeInTheDocument();
    expect(bodyOf(fetchMock, "POST /api/invites")).toEqual({ email: "new@example.org" });
    expect(fetchMock.mock.calls.filter(([u]) => String(u) === "/api/invites").length).toBeGreaterThanOrEqual(3);
  });

  it("explains a full quota and disables sending", async () => {
    routes({ ...CSRF, "GET /api/invites": { ...INVITES, used: 10, left: 0 } });
    render(<InvitesPage />);
    expect(await screen.findByLabelText("Friend's email")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send invite" })).toBeDisabled();
    expect(screen.getByText(/used all your invites/)).toBeInTheDocument();
  });

  it("shows the server's refusal in words", async () => {
    routes({ ...CSRF, "GET /api/invites": INVITES, "POST /api/invites": () => json({ detail: "already_member" }, 409) });
    render(<InvitesPage />);
    await userEvent.type(await screen.findByLabelText("Friend's email"), "member@example.org");
    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already has an account");
  });

  it("revokes an unused invite", async () => {
    const fetchMock = routes({ ...CSRF, "GET /api/invites": INVITES, [`DELETE /api/invites/${I1}`]: () => new Response(null, { status: 204 }) });
    render(<InvitesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Revoke the invite to f***@example.org" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith(I1) && i?.method === "DELETE")).toBe(true));
  });
});

describe("downloads", () => {
  const item = (over = {}) => ({ id: D1, analysis_id: A1, file_name: "Asha_Rao_tailored.pdf", format: "pdf",
    job_title: "Senior Analyst", company: "Acme", created_at: AT, paid_with: "credit", credits: 1,
    expires_at: "2026-10-27T10:00:00Z", available: true, ...over });

  it("lists files and downloads one again for free", async () => {
    routes({ ...CSRF, "GET /api/downloads": { items: [item()], next_before: null },
      [`POST /api/downloads/${D1}/link`]: { url: "/api/downloads/file/abc", expires_at: AT, paid_with: "credit", credits_balance: 3 } });
    render(<DownloadsPage />);
    expect(await screen.findByText("Asha_Rao_tailored.pdf")).toBeInTheDocument();
    expect(screen.getByText(/Senior Analyst at Acme · PDF/)).toBeInTheDocument();
    expect(screen.getByText(/Kept until Oct 27, 2026/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Download Asha_Rao_tailored.pdf again" }));
    await waitFor(() => expect(openDownload).toHaveBeenCalledWith("/api/downloads/file/abc"));
  });

  it("deletes a file now after confirming", async () => {
    routes({ ...CSRF, "GET /api/downloads": { items: [item()], next_before: null },
      [`DELETE /api/downloads/${D1}`]: () => new Response(null, { status: 204 }) });
    render(<DownloadsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete Asha_Rao_tailored.pdf now" }));
    await userEvent.click(within(screen.getByRole("group", { name: /Confirm deleting/ })).getByRole("button", { name: "Delete now" }));
    expect(await screen.findByText("No longer kept")).toBeInTheDocument();
  });

  it("says when a file is gone", async () => {
    routes({ ...CSRF, "GET /api/downloads": { items: [item()], next_before: null },
      [`POST /api/downloads/${D1}/link`]: () => json({ detail: "file_expired" }, 410) });
    render(<DownloadsPage />);
    await userEvent.click(await screen.findByRole("button", { name: /again/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no longer keep that file");
    expect(openDownload).not.toHaveBeenCalled();
  });

  it("has an empty state", async () => {
    routes({ "GET /api/downloads": { items: [], next_before: null } });
    render(<DownloadsPage />);
    expect(await screen.findByText("No downloads yet")).toBeInTheDocument();
  });
});

describe("support", () => {
  const TICKET = { id: I1, category: "support", subject: "Can't download", status: "open", created_at: AT, updated_at: AT };

  it("sends a message and lists it", async () => {
    let sent = false;
    const fetchMock = routes({ ...CSRF, "GET /api/support/tickets": () => json(sent ? [TICKET] : []),
      "POST /api/support/tickets": () => { sent = true; return json(TICKET, 201); } });
    render(<SupportPage />);
    expect(await screen.findByText(/None yet/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Subject"), "Can't download");
    await userEvent.type(screen.getByLabelText(/Message/), "The PDF button spins.");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/We usually reply/)).toBeInTheDocument();
    expect(bodyOf(fetchMock, "POST /api/support/tickets")).toEqual({ category: "support", subject: "Can't download", body: "The PDF button spins." });
    expect(await screen.findByText("Can't download")).toBeInTheDocument();
  });

  it("the feedback button picks the feedback category", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    routes({ "GET /api/support/tickets": [] });
    render(<SupportPage />);
    await userEvent.click(screen.getByRole("button", { name: "Send feedback" }));
    expect(screen.getByLabelText("What's it about?")).toHaveValue("feedback");
    expect(screen.getByLabelText("Subject")).toHaveFocus();
  });

  it("links the grievance officer and answers common questions", async () => {
    routes({ "GET /api/support/tickets": [] });
    render(<SupportPage />);
    expect(screen.getByRole("link", { name: "Contact the grievance officer" })).toHaveAttribute("href", "/legal/grievance");
    expect(screen.getByText("Does Resume Tailor ever add experience I don't have?")).toBeInTheDocument();
  });
});
