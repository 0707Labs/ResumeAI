import { defineConfig, devices } from "@playwright/test";

import { E2E_WEBHOOK_SECRET } from "./e2e/helpers";

// End-to-end happy path against the real FastAPI backend in rules-only mode.
// Run with `npm run test:e2e`. Locally, servers already on :8000/:3000 are reused,
// so a backend you started with ANTHROPIC_API_KEY set will make the spec fail its
// rules-only check; stop it first.
// E2E_WEB_URL / E2E_API_URL run a second copy beside servers you already have on
// :3000/:8000 (e.g. http://localhost:3100 and http://localhost:8100). Use localhost, not
// 127.0.0.1: Next's dev server blocks its scripts for other hosts, so pages never hydrate.
// Stop any `next dev` already running in this folder first; Next allows one per folder.
const WEB = process.env.E2E_WEB_URL ?? "http://localhost:3000";
const API = process.env.E2E_API_URL ?? "http://localhost:8000";
const port = (url: string) => new URL(url).port;

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: WEB,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `backend/.venv/bin/uvicorn app.main:app --app-dir backend --port ${port(API)}`,
      cwd: "..",
      url: `${API}/health`,
      // Empty key = rules only: deterministic output, no network calls to Anthropic.
      env: {
        ANTHROPIC_API_KEY: "", CORS_ORIGINS: WEB, RT_PUBLIC_URL: WEB,
        // More magic links than 5 per 15 minutes (honoured on localhost only; see app/auth/ratelimit.py).
        RT_DEV_RATE_LIMIT_SCALE: "10",
        // Test-mode payments: webhooks signed by e2e/helpers.ts. The API key is never used
        // (checkout is answered in the browser), but the provider needs one to be built.
        DODO_ENVIRONMENT: "test", DODO_API_KEY: "e2e-not-used", DODO_WEBHOOK_SECRET: E2E_WEBHOOK_SECRET,
      },
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `npx next dev --port ${port(WEB)}`,
      url: WEB,
      // The browser calls this origin; Next proxies /api/* and /health to the backend.
      env: { RT_BACKEND_URL: API },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
