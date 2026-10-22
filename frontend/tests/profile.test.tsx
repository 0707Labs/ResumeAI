import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ResumesPage from "@/app/app/resumes/page";
import { PersonalTab } from "@/components/app/profile/PersonalTab";
import { PrivacyTab } from "@/components/app/profile/PrivacyTab";
import { ResumeTab } from "@/components/app/profile/ResumeTab";
import { SavedResumePicker } from "@/components/app/SavedResumePicker";
import { TabList } from "@/components/app/Tabs";
import { blankEntry, cleanForSave, nextBulletId, nextEntryId } from "@/lib/resumeEdit";
import type { Resume } from "@/lib/schemas";
import { useSession } from "@/lib/store";

import { jd, resume } from "./fixtures";
import { tailored } from "./reviewFixtures";

const router = { push: vi.fn(), replace: vi.fn(), refresh: vi.fn() };
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/app/profile",
  useSearchParams: () => search,
  useParams: () => ({}),
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

const R1 = "11111111-1111-4111-8111-111111111111";
const R2 = "22222222-2222-4222-8222-222222222222";
const T1 = "33333333-3333-4333-8333-333333333333";
const AT = "2026-10-20T10:00:00Z";
const summary = (id: string, title: string, is_default: boolean, version = 1) =>
  ({ id, title, is_default, version, created_at: AT, updated_at: AT });
const detail = (id: string, r: Resume, version = 1, shown = version) =>
  ({ ...summary(id, "Main", true, version), shown_version: shown, source: "upload", resume: r });
const CSRF = { "GET /api/auth/csrf": { csrf_token: "tok" } };
const PROFILE = { name: "Ada", email: "ada@example.com", phone: null, avatar_url: null, avatar_source: null };

beforeEach(() => { search = new URLSearchParams(); Object.values(router).forEach((f) => f.mockReset()); });
afterEach(() => vi.unstubAllGlobals());

// --- editing helpers ---------------------------------------------------------------------------

describe("resume edit helpers", () => {
  it("makes ids in the parser's shapes, never reusing one", () => {
    const entry = { ...resume.sections[0].entries[0], bullets: [{ id: "exp1.b1", text: "a" }, { id: "exp1.b4", text: "b" }] };
    expect(nextBulletId(entry)).toBe("exp1.b5");
    expect(nextBulletId({ ...entry, bullets: [] })).toBe("exp1.b1");
    expect(nextEntryId(resume, "experience")).toBe("exp2");
    expect(nextEntryId(resume, "projects")).toBe("proj1");
    expect(blankEntry(resume, "education").id).toBe("edu1");
  });

  it("drops empty bullets, trims, and rebuilds raw_text, keeping ids", () => {
    const r: Resume = structuredClone(resume);
    r.summary = "  Analyst  ";
    r.sections[0].entries[0].bullets.push({ id: "exp1.b2", text: "   " }, { id: "exp1.b3", text: " Built dashboards " });
    const out = cleanForSave(r);
    expect(out.sections[0].entries[0].bullets).toEqual([
      { id: "exp1.b1", text: "Cut weekly reporting time by 30% with SQL" }, { id: "exp1.b3", text: "Built dashboards" }]);
    expect(out.summary).toBe("Analyst");
    expect(out.raw_text).toContain("- Built dashboards");
    expect(out.raw_text).toContain("Data Analyst, Acme | Jan 2022 - Present");
  });
});

// --- tabs ----------------------------------------------------------------------------------------

describe("tabs", () => {
  it("moves with arrow keys, Home and End", async () => {
    const onSelect = vi.fn();
    render(<TabList label="Profile sections" tabs={["a", "b", "c"] as const} labels={{ a: "A", b: "B", c: "C" }}
      current="a" onSelect={onSelect} idPrefix="t" />);
    const a = screen.getByRole("tab", { name: "A" });
    expect(a).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "B" })).toHaveAttribute("tabindex", "-1");
    a.focus();
    await userEvent.keyboard("{ArrowRight}");
    await userEvent.keyboard("{ArrowLeft}");
    await userEvent.keyboard("{End}");
    // onSelect is a spy, so the selected tab stays A: Right -> B, Left (from B) -> A, End -> C.
    expect(onSelect.mock.calls.map((c) => c[0])).toEqual(["b", "a", "c"]);
  });
});

// --- personal ------------------------------------------------------------------------------------

describe("personal tab", () => {
  const PROVIDERS = { "GET /api/account/providers": { accounts: [], can_unlink: false, available: { google: false, github: false, email: true } } };

  it("saves name and phone", async () => {
    const fetchMock = routes({ ...CSRF, ...PROVIDERS, "GET /api/profile": PROFILE,
      "PATCH /api/profile": (init?: RequestInit) => json({ ...PROFILE, ...JSON.parse(String(init?.body)), phone: "+919876543210" }) });
    render(<PersonalTab linked={null} error={null} />);
    await userEvent.type(await screen.findByLabelText(/Phone/), "+91 98765 43210");
    expect(screen.getByLabelText(/how you sign in/)).toHaveAttribute("readonly");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
    expect(bodyOf(fetchMock, "PATCH /api/profile")).toEqual({ name: "Ada", phone: "+91 98765 43210" });
    expect(screen.getByLabelText(/Phone/)).toHaveValue("+919876543210");
  });

  it("refuses an oversized or unsupported picture before uploading", async () => {
    const fetchMock = routes({ ...CSRF, ...PROVIDERS, "GET /api/profile": PROFILE });
    const { container } = render(<PersonalTab linked={null} error={null} />);
    await screen.findByRole("button", { name: "Upload a picture" });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["x".repeat(10)], "a.svg", { type: "image/svg+xml" }), { applyAccept: false });
    expect(await screen.findByRole("alert")).toHaveTextContent(/PNG, JPEG, WebP or GIF/);
    await userEvent.upload(input, new File([new Uint8Array(2 * 1024 * 1024 + 1)], "big.png", { type: "image/png" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/over 2 MB/);
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/api/profile/avatar"))).toBe(false);
  });

  it("uploads and removes a picture", async () => {
    const withPic = { ...PROFILE, avatar_url: "/api/profile/avatar?v=abc", avatar_source: "upload" };
    routes({ ...CSRF, ...PROVIDERS, "GET /api/profile": PROFILE, "PUT /api/profile/avatar": withPic,
      "DELETE /api/profile/avatar": PROFILE });
    const { container } = render(<PersonalTab linked={null} error={null} />);
    await screen.findByRole("button", { name: "Upload a picture" });
    await userEvent.upload(container.querySelector('input[type="file"]') as HTMLInputElement,
      new File(["png"], "me.png", { type: "image/png" }));
    expect(await screen.findByText("Your uploaded picture.", { exact: false })).toBeInTheDocument();
    expect(container.querySelector("img")).toHaveAttribute("src", "/api/profile/avatar?v=abc");
    await userEvent.click(screen.getByRole("button", { name: "Use initials instead" }));
    expect(await screen.findByText("Your initials, for now.", { exact: false })).toBeInTheDocument();
    expect(router.refresh).toHaveBeenCalledTimes(2);  // the header picks up each change
  });
});

// --- resume details ------------------------------------------------------------------------------

describe("resume tab", () => {
  it("edits a bullet, adds one, and saves it as the next version", async () => {
    const fetchMock = routes({
      ...CSRF,
      "GET /api/resumes": [summary(R1, "Main", true)],
      [`GET /api/resumes/${R1}`]: detail(R1, resume),
      [`GET /api/resumes/${R1}/versions`]: [{ version: 1, source: "upload", file_name: "cv.pdf", created_at: AT }],
      [`POST /api/resumes/${R1}/versions`]: (init?: RequestInit) =>
        json({ ...detail(R1, JSON.parse(String(init?.body)).resume, 2), source: "edit" }, 201),
    });
    render(<ResumeTab />);
    const bullet = await screen.findByLabelText("Bullet 1, Data Analyst");
    expect(screen.getByRole("button", { name: "Save as version 2" })).toBeDisabled();
    await userEvent.clear(bullet);
    await userEvent.type(bullet, "Cut reporting time by 30%");
    await userEvent.click(screen.getByRole("button", { name: "Add a bullet to Data Analyst" }));
    expect(screen.getByLabelText("Bullet 2, Data Analyst")).toHaveFocus();  // ready to type
    await userEvent.keyboard("Built Tableau dashboards");
    await userEvent.click(screen.getByRole("button", { name: "Save as version 2" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved as a new version");
    const sent = bodyOf(fetchMock, `POST /api/resumes/${R1}/versions`);
    expect(sent.source).toBe("edit");
    expect(sent.resume.sections[0].entries[0].bullets).toEqual([
      { id: "exp1.b1", text: "Cut reporting time by 30%" }, { id: "exp1.b2", text: "Built Tableau dashboards" }]);
  });

  it("shows an older version and can restore it", async () => {
    const old: Resume = { ...resume, summary: "Old summary" };
    const fetchMock = routes({
      ...CSRF,
      "GET /api/resumes": [summary(R1, "Main", true, 2)],
      [`GET /api/resumes/${R1}`]: detail(R1, resume, 2),
      [`GET /api/resumes/${R1}?version=1`]: detail(R1, old, 2, 1),
      [`GET /api/resumes/${R1}/versions`]: [
        { version: 2, source: "edit", file_name: null, created_at: AT }, { version: 1, source: "upload", file_name: null, created_at: AT }],
      [`POST /api/resumes/${R1}/versions`]: () => json(detail(R1, old, 3), 201),
    });
    render(<ResumeTab />);
    await userEvent.click(await screen.findByRole("button", { name: "View" }));
    expect(await screen.findByText("Viewing version 1 of 2")).toBeInTheDocument();
    expect(screen.getByLabelText("Summary")).toHaveValue("Old summary");
    await userEvent.click(screen.getByRole("button", { name: "Restore this version" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Version 1 restored");
    expect(bodyOf(fetchMock, `POST /api/resumes/${R1}/versions`).resume.summary).toBe("Old summary");
  });

  it("offers an upload when there's no saved resume", async () => {
    routes({ "GET /api/resumes": [] });
    render(<ResumeTab />);
    expect(await screen.findByText("No saved resume yet")).toBeInTheDocument();
    expect(screen.getByTestId("dropzone")).toBeInTheDocument();
  });
});

// --- privacy -------------------------------------------------------------------------------------

describe("privacy tab", () => {
  const CONSENTS = {
    research: false, research_available: true,
    history: [{ purpose: "service", action: "granted", method: "signup", notice_version: "2026-11-v1", notice_url: "/legal/terms", at: AT }],
  };

  it("shows consent history and switches the research consent", async () => {
    const fetchMock = routes({ ...CSRF, "GET /api/account/consents": CONSENTS,
      "PUT /api/account/consents/research": { ...CONSENTS, research: true,
        history: [{ ...CONSENTS.history[0], purpose: "research", method: "account_settings" }, ...CONSENTS.history] } });
    render(<PrivacyTab />);
    const toggle = await screen.findByRole("switch", { name: "Help improve the product" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("cell", { name: "Terms of Service and Privacy Policy" })).toBeInTheDocument();
    await userEvent.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    expect(bodyOf(fetchMock, "PUT /api/account/consents/research")).toEqual({ granted: true });
    expect(screen.getByText(/Given in your settings/)).toBeInTheDocument();
  });

  it("downloads the export file", async () => {
    routes({ ...CSRF, "GET /api/account/consents": CONSENTS,
      "POST /api/account/export": () => new Response("{}", { headers: { "content-disposition": 'attachment; filename="x.json"' } }) });
    const create = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<PrivacyTab />);
    await userEvent.click(await screen.findByRole("button", { name: "Download my data" }));
    expect(await screen.findByText("Your file is downloading.")).toBeInTheDocument();
    expect(create).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    click.mockRestore();
  });

  it("explains the export limit", async () => {
    routes({ ...CSRF, "GET /api/account/consents": CONSENTS, "POST /api/account/export": () => json({ detail: "x" }, 429) });
    render(<PrivacyTab />);
    await userEvent.click(await screen.findByRole("button", { name: "Download my data" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/wait a minute/);
  });
});

// --- my resumes ----------------------------------------------------------------------------------

describe("my resumes", () => {
  const T = { id: T1, job_title: "Senior Analyst", company: "Acme", created_at: AT, ats_before: 60, ats_after: 75,
    status: "tailored", resume_id: null, content_available: true };

  it("lists base resumes and tailorings, and pages older ones", async () => {
    const T2 = { ...T, id: R2, job_title: "Older role" };
    routes({
      "GET /api/resumes": [summary(R1, "Main", true, 3)],
      "GET /api/tailorings": { items: [T], next_before: "cursor-1" },
      "GET /api/tailorings?before=cursor-1": { items: [T2], next_before: null },
    });
    render(<ResumesPage />);
    expect(await screen.findByText("Main", { selector: "span.truncate" })).toBeInTheDocument();
    expect(screen.getByText(/Version 3/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Main" })).toHaveAttribute("href", `/app/profile?tab=resume&resume=${R1}`);
    expect(await screen.findByText("Senior Analyst")).toBeInTheDocument();
    expect(screen.getByText(/ATS 60 → 75/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show older" }));
    expect(await screen.findByText("Older role")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show older" })).toBeNull();
  });

  it("deletes a tailoring after confirming", async () => {
    const fetchMock = routes({ ...CSRF, "GET /api/resumes": [], "GET /api/tailorings": { items: [T], next_before: null },
      [`DELETE /api/tailorings/${T1}`]: () => new Response(null, { status: 204 }) });
    render(<ResumesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete Senior Analyst" }));
    const group = screen.getByRole("group", { name: "Confirm deleting Senior Analyst" });
    await userEvent.click(within(group).getByRole("button", { name: "Delete it" }));
    await waitFor(() => expect(screen.queryByText("Senior Analyst")).toBeNull());
    expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith(T1) && i?.method === "DELETE")).toBe(true);
  });

  it("tailors again from an earlier tailoring's inputs", async () => {
    useSession.getState().clearAll();
    routes({ "GET /api/resumes": [], "GET /api/tailorings": { items: [T], next_before: null },
      [`GET /api/tailorings/${T1}`]: { ...T, resume, jd: { ...jd, raw_text: "Senior Analyst\n- SQL" }, tailored } });
    render(<ResumesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Tailor again for Senior Analyst" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/app/tailor"));
    const s = useSession.getState();
    expect(s.resume?.name).toBe("Asha Rao");
    expect([s.jobTitle, s.company]).toEqual(["Senior Analyst", "Acme"]);
    expect(s.jdText).toBe("Senior Analyst\n- SQL");
    expect(s.tailored).toBeNull();  // a fresh run
  });

  it("shows empty states", async () => {
    routes({ "GET /api/resumes": [], "GET /api/tailorings": { items: [], next_before: null } });
    render(<ResumesPage />);
    expect(await screen.findByText("No saved resumes")).toBeInTheDocument();
    expect(await screen.findByText("Nothing tailored yet")).toBeInTheDocument();
  });
});

// --- saved resume picker -------------------------------------------------------------------------

describe("saved resume picker", () => {
  it("starts from the default saved resume", async () => {
    routes({ "GET /api/resumes": [summary(R2, "Other", false), summary(R1, "Main", true)],
      [`GET /api/resumes/${R1}`]: detail(R1, resume) });
    const onPick = vi.fn();
    render(<SavedResumePicker onPick={onPick} />);
    expect(await screen.findByLabelText("Use a saved resume")).toHaveValue(R1);
    await userEvent.click(screen.getByRole("button", { name: "Use it" }));
    await waitFor(() => expect(onPick).toHaveBeenCalledWith(resume, "Main"));
  });

  it("shows nothing without saved resumes", async () => {
    routes({ "GET /api/resumes": [] });
    const { container } = render(<SavedResumePicker onPick={vi.fn()} />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
