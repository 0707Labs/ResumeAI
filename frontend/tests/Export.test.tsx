import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ExportPage from "@/app/app/export/page";
import { ApiError, api } from "@/lib/api";
import type { ExportPreview, Resume } from "@/lib/schemas";
import { useSession } from "@/lib/store";

import { analysis, jd, resume } from "./fixtures";
import { tailored, verified } from "./reviewFixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/app/export",
}));
const openDownload = vi.fn();
vi.mock("@/lib/download", () => ({ openDownload: (...a: unknown[]) => openDownload(...a) }));
const link = (paid_with: "credit" | "window" | "pass" | "pro", credits_balance = 0) => ({
  url: "/api/downloads/file/abc.def", expires_at: "2026-10-22T00:00:00Z", paid_with, credits_balance,
});

const finalResume: Resume = {
  ...resume,
  sections: [{ ...resume.sections[0], entries: [{ ...resume.sections[0].entries[0], bullets: [
    { id: "exp1.b1", text: verified.text },
    { id: "exp1.b2", text: "Partnered with product managers on A/B test readouts" },
  ] }] }],
};
const preview: ExportPreview = { resume: finalResume, changed_lines: [verified.text] };

beforeEach(() => {
  vi.restoreAllMocks();
  openDownload.mockReset();
  useSession.getState().clearAll();
  const s = useSession.getState();
  s.setResume(resume, { mode: "file", fileName: "cv.pdf" });
  s.setAnalyzed(jd, analysis);
  s.setTailored(tailored); // t2 (warning) and t3 (blocked) are flagged
  s.decide("t1", "approved");
});

const downloadButton = (fmt: "DOCX" | "PDF") => screen.getByRole("button", { name: new RegExp(`download ${fmt}`, "i") });

describe("Step 6: export", () => {
  it("can't download until flagged changes are resolved, and says why", async () => {
    vi.spyOn(api, "exportPreview").mockResolvedValue(preview);
    const requestDownload = vi.spyOn(api, "requestDownload");
    render(<ExportPage />);

    const panel = screen.getByTestId("export-panel");
    expect(within(panel).getByText(/flagged changes still need your decision/i)).toBeInTheDocument();
    expect(within(panel).getByText(/Led a churn dashboard/)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: /resolve them on the review page/i })).toHaveAttribute("href", "/app/review");
    expect(downloadButton("DOCX")).toBeDisabled();
    expect(downloadButton("PDF")).toBeDisabled();
    expect(downloadButton("DOCX")).toHaveAccessibleDescription(/still need your decision/i);
    expect(requestDownload).not.toHaveBeenCalled();
    // The preview is still available while you decide.
    expect(await screen.findByTestId("resume-document")).toBeInTheDocument();
  });

  it("previews exactly what downloads, with changed lines marked (and unmarkable)", async () => {
    const user = userEvent.setup();
    const previewSpy = vi.spyOn(api, "exportPreview").mockResolvedValue(preview);
    render(<ExportPage />);
    const doc = await screen.findByTestId("resume-document");
    expect(within(doc).getByText(verified.text)).toBeInTheDocument();
    expect(within(doc).getByText(verified.text).closest("[data-changed]")).toHaveTextContent(`Changed line: ${verified.text}`);
    expect(doc.querySelectorAll("[data-changed]")).toHaveLength(1);

    await user.click(screen.getByLabelText(/mark changed lines/i));
    expect(doc.querySelectorAll("[data-changed]")).toHaveLength(0);

    // The preview request carries your decisions.
    const sent = previewSpy.mock.calls[0][1];
    expect(sent.bullets.map((b) => b.review)).toEqual(["approved", "pending", "pending", "pending"]);
  });

  it("downloads once resolved, using only approved changes", async () => {
    const user = userEvent.setup();
    useSession.getState().decide("t2", "rejected");
    useSession.getState().decide("t3", "rejected");
    vi.spyOn(api, "exportPreview").mockResolvedValue(preview);
    const requestDownload = vi.spyOn(api, "requestDownload").mockResolvedValue(link("credit", 2));

    render(<ExportPage />);
    expect(screen.getByText(/1 approved change included/i)).toBeInTheDocument();
    await user.click(downloadButton("DOCX"));

    await waitFor(() => expect(openDownload).toHaveBeenCalledWith("/api/downloads/file/abc.def"));
    const [fmt, , , sent] = requestDownload.mock.calls[0];
    expect(fmt).toBe("docx");
    expect(sent.bullets.map((b) => [b.id, b.review])).toEqual([
      ["t1", "approved"], ["t2", "rejected"], ["t3", "rejected"], ["t4", "pending"],
    ]);
    expect(await screen.findByText(/1 credit used; 2 left/)).toBeInTheDocument();
  });

  it("shows a friendly error if the download fails", async () => {
    const user = userEvent.setup();
    useSession.getState().decide("t2", "approved");
    useSession.getState().decide("t3", "rejected");
    vi.spyOn(api, "exportPreview").mockResolvedValue(preview);
    vi.spyOn(api, "requestDownload").mockRejectedValue(new ApiError("backend_down", 0));
    render(<ExportPage />);
    await user.click(downloadButton("PDF"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/can't reach the analysis service/i);
    expect(openDownload).not.toHaveBeenCalled();
  });

  it("signed out: asks to sign in to download, and comes back here after", async () => {
    const user = userEvent.setup();
    useSession.getState().decide("t2", "approved");
    useSession.getState().decide("t3", "rejected");
    vi.spyOn(api, "exportPreview").mockResolvedValue(preview);
    vi.spyOn(api, "requestDownload").mockRejectedValue(new ApiError("sign_in_required", 401));
    render(<ExportPage />);
    await user.click(downloadButton("DOCX"));
    expect(await screen.findByText("Sign in to download")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/signin?next=/app/export");
    expect(screen.queryByText("Download didn't finish")).not.toBeInTheDocument();
    expect(openDownload).not.toHaveBeenCalled();
  });

  it("sends nothing anywhere but our own origin (proxied to the backend)", async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL) => new Response(JSON.stringify(preview)));
    vi.stubGlobal("fetch", fetchMock);
    render(<ExportPage />);
    await screen.findByTestId("resume-document");
    expect(fetchMock).toHaveBeenCalled();
    expect(fetchMock.mock.calls.every(([url]) => String(url).startsWith("/api/"))).toBe(true);
    vi.unstubAllGlobals();
  });

  it("back from checkout: finishes the download that needed paying for, once", async () => {
    useSession.getState().decide("t2", "approved");
    useSession.getState().decide("t3", "rejected");
    vi.spyOn(api, "exportPreview").mockResolvedValue(preview);
    const requestDownload = vi.spyOn(api, "requestDownload").mockResolvedValue(link("credit", 4));
    sessionStorage.setItem("rt:pending-download", JSON.stringify({ fmt: "pdf", at: Date.now() }));
    window.history.replaceState(null, "", "/app/export?resume=download");
    const { rerender } = render(<ExportPage />);
    await waitFor(() => expect(openDownload).toHaveBeenCalledWith("/api/downloads/file/abc.def"));
    expect(requestDownload.mock.calls[0][0]).toBe("pdf");
    expect(window.location.search).toBe("");
    rerender(<ExportPage />);
    expect(requestDownload).toHaveBeenCalledOnce();
    expect(sessionStorage.getItem("rt:pending-download")).toBeNull();
  });
});

