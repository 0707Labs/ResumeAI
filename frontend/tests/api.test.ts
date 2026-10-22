import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, classify, dailyLimitNote, messageFor } from "@/lib/api";

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

describe("analysis id and the download paywall", () => {
  const started = (id: string) => ({ analysis_id: id, usable_until: "2026-10-22T00:00:00Z", uses: "free" });
  const ids = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"];
  const pdf = () => new Response(JSON.stringify({
    url: "/api/downloads/file/abc.def", expires_at: "2026-10-22T00:00:00Z", paid_with: "credit", credits_balance: 2,
  }));

  function backend(analyses: () => Response, exportRes: () => Response = pdf) {
    const fetchMock = vi.fn(async (url: RequestInfo | URL, ..._rest: [RequestInit?]) => {
      if (String(url) === "/api/auth/csrf") return new Response(JSON.stringify({ csrf_token: "t" }));
      if (String(url) === "/api/analyses") return analyses();
      if (String(url).startsWith("/api/downloads/")) return exportRes();
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const calls = (path: string) => fetchMock.mock.calls.filter((c) => String(c[0]).startsWith(path));
    const pipeline = () => fetchMock.mock.calls.filter((c) => !/\/api\/(auth|analyses)/.test(String(c[0])));
    const header = (i: number) => (pipeline()[i][1]?.headers ?? {}) as Record<string, string>;
    return { calls, header };
  }

  afterEach(() => sessionStorage.clear());

  const gapBody = (notes: string[]) => ({
    items: [], candidate_years_experience: null, notes, counts: { evidenced: 0, implied: 0, missing: 0 }, required_coverage: 0,
  });
  const withStart = (startBody: object, notes: string[]) => vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => {
    if (String(url) === "/api/auth/csrf") return new Response(JSON.stringify({ csrf_token: "t" }));
    if (String(url) === "/api/analyses") return new Response(JSON.stringify(startBody));
    return new Response(JSON.stringify(gapBody(notes)));
  }));

  it("over the daily Claude cap: the analysis still starts, and the note says why it's rules-only", async () => {
    withStart({ ...started(ids[0]), claude: false, claude_per_day: 10 },
      ["Rules only (today's Claude analyses are used up; more from 00:00 UTC)."]);
    const gap = await api.analyze({} as never, {} as never);
    expect(sessionStorage.getItem("rt_analysis_id")).toBe(ids[0]);
    expect(gap.notes).toEqual([dailyLimitNote(10)]);
    expect(gap.notes[0]).toMatch(/today's 10 Claude analyses.*00:00 UTC/);
  });

  it("under the cap the gap notes are left alone", async () => {
    withStart({ ...started(ids[0]), claude: true, claude_per_day: 10 }, ["Refined with Claude."]);
    expect((await api.analyze({} as never, {} as never)).notes).toEqual(["Refined with Claude."]);
  });

  it("429 on start is a rate-limit message, not bad input", async () => {
    backend(() => new Response(JSON.stringify({ detail: "rate_limited" }), { status: 429 }));
    const err = await api.analyze({} as never, {} as never).catch((e) => e);
    expect(err.kind).toBe("rate_limited");
    expect(classify(429)).toBe("rate_limited");
  });

  it("analyze starts a server-side analysis with the inputs; later calls send its id", async () => {
    let n = 0;
    const { calls, header } = backend(() => new Response(JSON.stringify(started(ids[n++]))));
    await api.analyze({ name: "R" } as never, { raw_text: "J" } as never).catch(() => undefined);
    const [start] = calls("/api/analyses");
    expect((start[1]?.headers as Record<string, string>)["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(JSON.parse(String(start[1]?.body))).toEqual({ resume: { name: "R" }, jd: { raw_text: "J" } });
    expect(header(0)["X-Analysis-Id"]).toBe(ids[0]);
    await api.mentor({} as never, {} as never, {} as never).catch(() => undefined);
    expect(header(1)["X-Analysis-Id"]).toBe(ids[0]);
    await api.analyze({} as never, {} as never).catch(() => undefined);
    expect(header(2)["X-Analysis-Id"]).toBe(ids[1]);
  });

  it("signed out: no analysis id, rules-only, and the download asks to sign in", async () => {
    sessionStorage.setItem("rt_analysis_id", ids[0]);
    const { calls, header } = backend(() => new Response(JSON.stringify({ detail: "not_signed_in" }), { status: 401 }));
    await api.analyze({} as never, {} as never).catch(() => undefined);
    expect(header(0)["X-Analysis-Id"]).toBeUndefined();
    const err = await api.requestDownload("pdf", {} as never, { raw_text: "J" } as never, {} as never, null)
      .catch((e: ApiError) => e);
    expect((err as ApiError).kind).toBe("sign_in_required");
    expect(calls("/api/downloads/")).toHaveLength(0);
  });

  it("signed in after analyzing: the download starts an analysis first", async () => {
    const { calls } = backend(() => new Response(JSON.stringify(started(ids[0]))));
    const out = await api.requestDownload("pdf", {} as never, { raw_text: "J" } as never, {} as never, null);
    expect([out.url, out.paid_with]).toEqual(["/api/downloads/file/abc.def", "credit"]);
    const [exp] = calls("/api/downloads/pdf");
    expect((exp[1]?.headers as Record<string, string>)["X-Analysis-Id"]).toBe(ids[0]);
    expect((exp[1]?.headers as Record<string, string>)["X-CSRF-Token"]).toBe("t");
  });

  it("402 on download opens the pricing dialog for that download", async () => {
    sessionStorage.setItem("rt_analysis_id", ids[0]);
    const opened = vi.fn();
    window.addEventListener("rt:out-of-credits", opened);
    backend(() => new Response("{}"), () => new Response(JSON.stringify({ detail: "no_credits" }), { status: 402 }));
    const err = await api.requestDownload("docx", {} as never, { raw_text: "J" } as never, {} as never, null)
      .catch((e: ApiError) => e);
    window.removeEventListener("rt:out-of-credits", opened);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).kind).toBe("out_of_credits");
    expect(opened).toHaveBeenCalledOnce();
    expect((opened.mock.calls[0][0] as CustomEvent).detail).toEqual({ reason: "download", fmt: "docx" });
  });

  it("410 analysis_expired: says the window has passed and forgets the purged analysis", async () => {
    sessionStorage.setItem("rt_analysis_id", ids[0]);
    backend(() => new Response("{}"), () => new Response(JSON.stringify({ detail: "analysis_expired" }), { status: 410 }));
    const err = await api.requestDownload("pdf", {} as never, { raw_text: "J" } as never, {} as never, null)
      .catch((e: ApiError) => e);
    expect((err as ApiError).kind).toBe("analysis_expired");
    expect((err as ApiError).message).toMatch(/re-download period .* has passed.*Tailor it again/);
    expect(sessionStorage.getItem("rt_analysis_id")).toBeNull();
  });

  it("402 on analyze: past the free tailorings, the pricing dialog opens for tailoring", async () => {
    const opened = vi.fn();
    window.addEventListener("rt:out-of-credits", opened);
    backend(() => new Response(JSON.stringify({ detail: "no_credits" }), { status: 402 }));
    const err = await api.analyze({} as never, {} as never).catch((e: ApiError) => e);
    window.removeEventListener("rt:out-of-credits", opened);
    expect((err as ApiError).kind).toBe("tailoring_limit");
    expect((opened.mock.calls[0][0] as CustomEvent).detail).toEqual({ reason: "tailoring" });
  });
});
