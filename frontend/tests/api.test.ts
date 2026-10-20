import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, classify, messageFor } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

const respond = (status: number, body: unknown) =>
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));

describe("classify", () => {
  it.each([
    [415, undefined, "unsupported_file"],
    [413, undefined, "file_too_large"],
    [422, "No text found. If this is a scanned image PDF, ...", "no_text"],
    [422, "Could not read this PDF.", "unreadable_file"],
    [422, "text: too short", "invalid_input"],
    [500, undefined, "server"],
  ])("%i %s -> %s", (status, detail, kind) => {
    expect(classify(status, detail)).toBe(kind);
  });
});

describe("request errors", () => {
  it("backend down becomes a friendly message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const err = await api.parseJD("x".repeat(30)).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.kind).toBe("backend_down");
    expect(messageFor(err)).toMatch(/can't reach the analysis service/i);
  });

  it("scanned PDF explains what to do", async () => {
    respond(422, { detail: "No text found. If this is a scanned image PDF, export a text-based PDF..." });
    const err = await api.parseResumeFile(new File(["%PDF-"], "scan.pdf")).catch((e) => e);
    expect(err.kind).toBe("no_text");
    expect(err.message).toMatch(/scanned image/);
    expect(err.message).toMatch(/paste your resume as text/);
  });

  it("rejects a response that doesn't match the schema", async () => {
    respond(200, { title: "x" }); // missing most JobDescription fields
    const err = await api.parseJD("x".repeat(30)).catch((e) => e);
    expect(err.kind).toBe("bad_response");
    expect(err.detail).toMatch(/requirements|seniority/);
  });

  it("only ever calls our backend", async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL) => new Response(JSON.stringify({ status: "ok", llm_configured: false })));
    vi.stubGlobal("fetch", fetchMock);
    await api.health();
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://localhost:8000/health");
  });
});
