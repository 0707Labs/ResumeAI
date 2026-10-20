import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { UploadDropzone, checkFile } from "@/components/UploadDropzone";

const file = (name: string, size = 10) => new File(["x".repeat(size)], name);

describe("checkFile", () => {
  it("accepts PDF and DOCX", () => {
    expect(checkFile(file("cv.pdf"))).toBeNull();
    expect(checkFile(file("CV.DOCX"))).toBeNull();
  });
  it("explains unsupported types and suggests pasting", () => {
    expect(checkFile(file("cv.png"))).toMatch(/isn't a PDF or DOCX.*paste/);
  });
  it("rejects files over 5 MB", () => {
    expect(checkFile(file("big.pdf", 5 * 1024 * 1024 + 1))).toMatch(/over 5 MB/);
  });
});

describe("UploadDropzone", () => {
  it("is keyboard operable through a labelled button", async () => {
    render(<UploadDropzone onFile={vi.fn()} onReject={vi.fn()} />);
    const button = screen.getByRole("button", { name: /choose a file/i });
    await userEvent.tab();
    expect(button).toHaveFocus();
    expect(button).toHaveAccessibleDescription(/PDF or DOCX, up to 5 MB/);
  });

  it("hands valid drops to onFile and invalid ones to onReject", () => {
    const onFile = vi.fn();
    const onReject = vi.fn();
    render(<UploadDropzone onFile={onFile} onReject={onReject} />);
    const zone = screen.getByTestId("dropzone");

    fireEvent.drop(zone, { dataTransfer: { files: [file("cv.pdf")] } });
    expect(onFile).toHaveBeenCalledOnce();

    fireEvent.drop(zone, { dataTransfer: { files: [file("photo.jpg")] } });
    expect(onReject).toHaveBeenCalledWith(expect.stringMatching(/photo\.jpg/));
    expect(onFile).toHaveBeenCalledOnce();
  });

  it("uses the file picker too", async () => {
    const onFile = vi.fn();
    render(<UploadDropzone onFile={onFile} onReject={vi.fn()} />);
    await userEvent.upload(screen.getByTestId("file-input"), file("cv.docx"));
    expect(onFile).toHaveBeenCalledWith(expect.objectContaining({ name: "cv.docx" }));
  });

  it("shows progress and blocks new files while busy", () => {
    const onFile = vi.fn();
    render(<UploadDropzone onFile={onFile} onReject={vi.fn()} busy />);
    expect(screen.getByText(/reading your resume/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /choose a file/i })).toBeDisabled();
    fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [file("cv.pdf")] } });
    expect(onFile).not.toHaveBeenCalled();
  });
});
