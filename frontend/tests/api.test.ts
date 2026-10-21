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

  it("only ever calls our own origin (proxied to the backend)", async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL) => new Response(JSON.stringify({ status: "ok", llm_configured: false })));
    vi.stubGlobal("fetch", fetchMock);
    await api.health();
    expect(String(fetchMock.mock.calls[0][0])).toBe("/health");
  });
});

describe("session", () => {
  const USER = { id: "0b6f1d9e-2c4a-4f7b-9d1e-3a5c7e9f1b2d", email: "ada@example.com", name: null, role: "user", status: "active" };

  afterEach(() => {
    document.cookie = "rt_csrf=; max-age=0; path=/";
  });

  it("me() is the validated user, or null when signed out", async () => {
    respond(200, USER);
    expect(await api.me()).toEqual(USER);
    respond(401, { detail: "not_signed_in" });
    expect(await api.me()).toBeNull();
  });

  it("me() still surfaces other failures", async () => {
    respond(500, {});
    expect((await api.me().catch((e) => e)).kind).toBe("server");
  });

  it("logout echoes the CSRF cookie in the header", async () => {
    document.cookie = "rt_csrf=tok-123; path=/";
    const fetchMock = vi.fn(async (..._args: [RequestInfo | URL, RequestInit?]) => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await api.logout();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/auth/logout");
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok-123");
  });

  it("logout fetches a CSRF token first when there is no cookie", async () => {
    const fetchMock = vi.fn(async (url: RequestInfo | URL, ..._rest: [RequestInit?]) =>
      String(url) === "/api/auth/csrf"
        ? new Response(JSON.stringify({ csrf_token: "fresh" }))
        : new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await api.logout();
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).toEqual(["/api/auth/csrf", "/api/auth/logout"]);
    expect((fetchMock.mock.calls[1][1]?.headers as Record<string, string>)["X-CSRF-Token"]).toBe("fresh");
  });
});

describe("analysis id", () => {
  it("starts a new id on analyze and sends it with later pipeline calls", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({}), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const header = (i: number) => (fetchMock.mock.calls[i] as unknown as [string, RequestInit])[1].headers as Record<string, string>;
    await api.analyze({} as never, {} as never).catch(() => undefined);
    const first = header(0)["X-Analysis-Id"];
    expect(first).toMatch(/^[0-9a-f-]{36}$/);
    await api.mentor({} as never, {} as never, {} as never).catch(() => undefined);
    expect(header(1)["X-Analysis-Id"]).toBe(first);
    await api.analyze({} as never, {} as never).catch(() => undefined);
    expect(header(2)["X-Analysis-Id"]).not.toBe(first);
    vi.unstubAllGlobals();
  });
});
