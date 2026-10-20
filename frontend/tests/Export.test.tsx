import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ExportPage from "@/app/export/page";
import { ApiError, api } from "@/lib/api";
import type { ExportPreview, Resume } from "@/lib/schemas";
import { useSession } from "@/lib/store";

import { analysis, jd, resume } from "./fixtures";
import { tailored, verified } from "./reviewFixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/export",
}));
const saveBlob = vi.fn();
vi.mock("@/lib/download", () => ({ saveBlob: (...a: unknown[]) => saveBlob(...a) }));

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
  saveBlob.mockReset();
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
    const exportFile = vi.spyOn(api, "exportFile");
    render(<ExportPage />);

    const panel = screen.getByTestId("export-panel");
    expect(within(panel).getByText(/flagged changes still need your decision/i)).toBeInTheDocument();
    expect(within(panel).getByText(/Led a churn dashboard/)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: /resolve them on the review page/i })).toHaveAttribute("href", "/review");
    expect(downloadButton("DOCX")).toBeDisabled();
    expect(downloadButton("PDF")).toBeDisabled();
    expect(downloadButton("DOCX")).toHaveAccessibleDescription(/still need your decision/i);
    expect(exportFile).not.toHaveBeenCalled();
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
    const blob = new Blob(["docx"]);
    const exportFile = vi.spyOn(api, "exportFile").mockResolvedValue({ blob, filename: "Asha_Rao_tailored.docx" });

    render(<ExportPage />);
    expect(screen.getByText(/1 approved change included/i)).toBeInTheDocument();
    await user.click(downloadButton("DOCX"));

    await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(blob, "Asha_Rao_tailored.docx"));
    const [fmt, , sent] = exportFile.mock.calls[0];
    expect(fmt).toBe("docx");
    expect(sent.bullets.map((b) => [b.id, b.review])).toEqual([
      ["t1", "approved"], ["t2", "rejected"], ["t3", "rejected"], ["t4", "pending"],
    ]);
    expect(await screen.findByText("Asha_Rao_tailored.docx")).toBeInTheDocument();
  });

  it("shows a friendly error if the download fails", async () => {
    const user = userEvent.setup();
    useSession.getState().decide("t2", "approved");
    useSession.getState().decide("t3", "rejected");
    vi.spyOn(api, "exportPreview").mockResolvedValue(preview);
    vi.spyOn(api, "exportFile").mockRejectedValue(new ApiError("backend_down", 0));
    render(<ExportPage />);
    await user.click(downloadButton("PDF"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/can't reach the analysis service/i);
    expect(saveBlob).not.toHaveBeenCalled();
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
});
