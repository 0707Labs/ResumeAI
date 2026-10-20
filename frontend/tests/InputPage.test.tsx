import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { STORAGE_KEY, useSession } from "@/lib/store";
import InputPage from "@/app/page";

import { JD_TEXT, analysis, jd, resume } from "./fixtures";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/",
}));

beforeEach(() => {
  vi.restoreAllMocks();
  push.mockReset();
  useSession.getState().clearAll();
});

async function fillJD(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByLabelText(/job description/i));
  await user.paste(JD_TEXT);
}

describe("Step 1: input screen", () => {
  it("shows the trust note", () => {
    render(<InputPage />);
    expect(screen.getByText("We never add experience you don't have. You approve every change.")).toBeInTheDocument();
  });

  it("explains why Analyze is disabled", async () => {
    render(<InputPage />);
    const button = screen.getByRole("button", { name: /analyze/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(/upload your resume.*paste the job description/i);
  });

  it("happy path: upload, paste JD with my title, analyze, go to /analysis", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "parseResumeFile").mockResolvedValue(resume);
    vi.spyOn(api, "parseJD").mockResolvedValue({ ...jd, title: "Analyst (guessed)" });
    const analyze = vi.spyOn(api, "analyze").mockResolvedValue(analysis);

    render(<InputPage />);
    await user.upload(screen.getByTestId("file-input"), new File(["%PDF-"], "cv.pdf"));
    expect(await screen.findByText(/here's what we read/i)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/job title/i), "Senior Data Analyst");
    await fillJD(user);
    await user.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/analysis"));
    // The user's title overrides the parser's guess.
    expect(analyze.mock.calls[0][1].title).toBe("Senior Data Analyst");
    expect(useSession.getState().analysis).toEqual(analysis);
  });

  it("paste fallback: text is parsed on Analyze without a separate check", async () => {
    const user = userEvent.setup();
    const parseText = vi.spyOn(api, "parseResumeText").mockResolvedValue(resume);
    vi.spyOn(api, "parseJD").mockResolvedValue(jd);
    vi.spyOn(api, "analyze").mockResolvedValue(analysis);

    render(<InputPage />);
    await user.click(screen.getByRole("tab", { name: /paste text/i }));
    await user.click(screen.getByLabelText(/resume text/i));
    await user.paste("Asha Rao\nExperience\n• Did things");
    await fillJD(user);
    await user.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/analysis"));
    expect(parseText).toHaveBeenCalledWith("Asha Rao\nExperience\n• Did things");
  });

  it("tabs work with arrow keys", async () => {
    const user = userEvent.setup();
    render(<InputPage />);
    const upload = screen.getByRole("tab", { name: /upload a file/i });
    upload.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: /paste text/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /paste text/i })).toHaveFocus();
  });

  it("unsupported file is caught before upload", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const parse = vi.spyOn(api, "parseResumeFile");
    render(<InputPage />);
    await user.upload(screen.getByTestId("file-input"), new File(["x"], "cv.pages"));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/isn't a PDF or DOCX/)).toBeInTheDocument();
    expect(parse).not.toHaveBeenCalled();
  });

  it("scanned PDF error is shown in plain words", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "parseResumeFile").mockRejectedValue(new ApiError("no_text", 422));
    render(<InputPage />);
    await user.upload(screen.getByTestId("file-input"), new File(["%PDF-"], "scan.pdf"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/scanned image/);
  });

  it("backend down during analysis keeps the user's input", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "parseResumeFile").mockResolvedValue(resume);
    vi.spyOn(api, "parseJD").mockRejectedValue(new ApiError("backend_down", 0));
    render(<InputPage />);
    await user.upload(screen.getByTestId("file-input"), new File(["%PDF-"], "cv.pdf"));
    await screen.findByText(/here's what we read/i);
    await fillJD(user);
    await user.click(screen.getByRole("button", { name: /analyze/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/can't reach the analysis service/i);
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/job description/i)).toHaveValue(JD_TEXT);
  });
});

describe("session store", () => {
  it("persists to sessionStorage and clears completely", () => {
    useSession.getState().setResume(resume, { mode: "file", fileName: "cv.pdf" });
    expect(sessionStorage.getItem(STORAGE_KEY)).toContain("Asha Rao");
    useSession.getState().clearAll();
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(useSession.getState().resume).toBeNull();
  });

  it("a new resume invalidates the old analysis", () => {
    const s = useSession.getState();
    s.setResume(resume, { mode: "file", fileName: "a.pdf" });
    s.setAnalyzed(jd, analysis);
    useSession.getState().setResume(resume, { mode: "file", fileName: "b.pdf" });
    expect(useSession.getState().analysis).toBeNull();
  });
});
