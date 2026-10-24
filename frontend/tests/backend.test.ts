import { describe, expect, it } from "vitest";

import { backendUrl } from "@/lib/backend";

describe("backendUrl", () => {
  it("reads BACKEND_URL, then the old RT_BACKEND_URL", () => {
    expect(backendUrl({ BACKEND_URL: "http://backend.railway.internal:8080/" })).toBe("http://backend.railway.internal:8080");
    expect(backendUrl({ RT_BACKEND_URL: "http://localhost:8100" })).toBe("http://localhost:8100");
    expect(backendUrl({ BACKEND_URL: "https://a.example", RT_BACKEND_URL: "https://b.example" })).toBe("https://a.example");
  });

  it("defaults to localhost:8000 outside production", () => {
    expect(backendUrl({})).toBe("http://localhost:8000");
    expect(backendUrl({ NODE_ENV: "development", BACKEND_URL: " " })).toBe("http://localhost:8000");
  });

  it("refuses a production build or server without it", () => {
    expect(() => backendUrl({ NODE_ENV: "production" })).toThrow(/BACKEND_URL must be set/);
  });

  it("refuses anything but an http(s) origin", () => {
    expect(() => backendUrl({ BACKEND_URL: "backend:8080" })).toThrow(/http\(s\)/);
    expect(() => backendUrl({ BACKEND_URL: "not a url" })).toThrow(/not a URL/);
    expect(() => backendUrl({ BACKEND_URL: "http://backend.internal/api" })).toThrow(/origin only/);
  });
});
