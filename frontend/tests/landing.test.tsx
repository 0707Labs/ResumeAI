import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import InvitePage from "@/app/signup/invite/page";
import { INVITE_CODE_KEY } from "@/components/site/SignUpButton";
import { SiteHeader } from "@/components/site/SiteHeader";
import { getPublicConfig } from "@/lib/site";

const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const ME = { id: "6f1d2c1e-8a4b-4f7e-9a51-1c2d3e4f5a6b", email: "ada@example.com", name: null, role: "user", status: "active", capabilities: [], onboarded: true, avatar_url: null };

function stubFetch(table: Record<string, () => Response>) {
  const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(url)}`;
    const hit = Object.keys(table).find((k) => key.endsWith(k));
    if (!hit) throw new Error(`unrouted ${key}`);
    return table[hit]();
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  router.push.mockReset();
  router.replace.mockReset();
  sessionStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "rt_csrf=; path=/; max-age=0";
});

describe("site header", () => {
  it("offers Sign in and a plain Sign up link when signup is open", async () => {
    stubFetch({ "GET /api/me": () => json({ detail: "not_signed_in" }, 401) });
    render(<SiteHeader inviteOnly={false} initialTheme="system" />);
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/signin");
    expect(screen.getByRole("link", { name: "Sign up" })).toHaveAttribute("href", "/signup");
    expect(screen.getByRole("radiogroup", { name: "Color theme" })).toBeInTheDocument();
  });

  it("doesn't ask /api/me when there's no sign-in cookie (no 401 for new visitors)", () => {
    const fetchMock = stubFetch({ "GET /api/auth/config": () => json({ invite_only: true }) });
    render(<SiteHeader inviteOnly={false} initialTheme="system" />);
    expect(fetchMock.mock.calls.map(([url]) => String(url)).filter((u) => u.endsWith("/api/me"))).toEqual([]);
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
  });

  it("links How it works, Pricing and FAQ to their sections", () => {
    stubFetch({ "GET /api/me": () => json({ detail: "not_signed_in" }, 401) });
    render(<SiteHeader inviteOnly={false} initialTheme="system" />);
    expect(screen.getByRole("link", { name: "How it works" })).toHaveAttribute("href", "/#how-it-works");
    expect(screen.getByRole("link", { name: "Pricing" })).toHaveAttribute("href", "/#pricing");
    expect(screen.getByRole("link", { name: "FAQ" })).toHaveAttribute("href", "/#faq");
  });

  it("opens a phone menu with the links and account actions, and Escape closes it", async () => {
    stubFetch({ "GET /api/me": () => json({ detail: "not_signed_in" }, 401) });
    render(<SiteHeader inviteOnly={false} initialTheme="system" />);
    const toggle = screen.getByRole("button", { name: "Open menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById("site-menu")).toBeNull();

    await userEvent.click(toggle);
    const menu = document.getElementById("site-menu")!;
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAccessibleName("Close menu");
    for (const name of ["How it works", "Pricing", "FAQ", "Sign in", "Sign up"]) {
      expect(within(menu).getByRole("link", { name })).toBeInTheDocument();
    }
    expect(within(menu).getByRole("link", { name: "How it works" })).toHaveFocus();

    await userEvent.keyboard("{Escape}");
    expect(document.getElementById("site-menu")).toBeNull();
    expect(toggle).toHaveFocus();
  });

  it("closes the phone menu when a section link is followed", async () => {
    stubFetch({ "GET /api/me": () => json({ detail: "not_signed_in" }, 401) });
    render(<SiteHeader inviteOnly={false} initialTheme="system" />);
    await userEvent.click(screen.getByRole("button", { name: "Open menu" }));
    await userEvent.click(within(document.getElementById("site-menu")!).getByRole("link", { name: "FAQ" }));
    expect(document.getElementById("site-menu")).toBeNull();
  });

  it("swaps to Open workspace for a signed-in visitor", async () => {
    document.cookie = "rt_csrf=t; path=/";
    stubFetch({ "GET /api/me": () => json(ME) });
    render(<SiteHeader inviteOnly initialTheme="system" />);
    expect(await screen.findByRole("link", { name: "Open workspace" })).toHaveAttribute("href", "/app");
    expect(screen.queryByRole("link", { name: "Sign in" })).not.toBeInTheDocument();
  });

  it("in invite-only mode, Sign up asks for an invite code or points to the waitlist", async () => {
    stubFetch({ "GET /api/me": () => json({ detail: "not_signed_in" }, 401) });
    render(<SiteHeader inviteOnly initialTheme="system" />);
    await userEvent.click(screen.getByRole("button", { name: "Sign up" }));

    expect(screen.getByRole("heading", { name: "Resume Tailor is invite-only for now" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Join the waitlist" })).toHaveAttribute("href", "/waitlist");

    await userEvent.click(screen.getByRole("button", { name: "Continue to sign up" }));
    expect(screen.getByText(/Enter your invite code/)).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText(/Invite code/), " abcd-efgh-jklm ");
    await userEvent.click(screen.getByRole("button", { name: "Continue to sign up" }));
    expect(sessionStorage.getItem(INVITE_CODE_KEY)).toBe("abcd-efgh-jklm");
    expect(router.push).toHaveBeenCalledWith("/signup");
  });
});

describe("invite step", () => {
  it("pre-fills the code typed on the landing page", async () => {
    sessionStorage.setItem(INVITE_CODE_KEY, "ABCD-EFGH-JKLM");
    stubFetch({
      "GET /api/auth/pending": () => json({
        kind: "signup", provider: "email", email: "ada@example.com",
        invite_required: true, invite_accepted: false, has_bound_invite: false,
      }),
    });
    render(<InvitePage />);
    expect(await screen.findByLabelText(/Invite code/)).toHaveValue("ABCD-EFGH-JKLM");
  });
});

describe("public config", () => {
  it("reads the invite-only flag from the backend", async () => {
    stubFetch({ "GET http://localhost:8000/api/auth/config": () => json({ invite_only: false }) });
    expect(await getPublicConfig()).toEqual({ invite_only: false });
  });

  it("stays invite-only when the backend can't be reached or answers nonsense", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    expect(await getPublicConfig()).toEqual({ invite_only: true });
    stubFetch({ "GET http://localhost:8000/api/auth/config": () => json({ nope: 1 }) });
    expect(await getPublicConfig()).toEqual({ invite_only: true });
  });
});
