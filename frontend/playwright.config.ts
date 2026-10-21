import { defineConfig, devices } from "@playwright/test";

// End-to-end happy path against the real FastAPI backend in rules-only mode.
// Run with `npm run test:e2e`. Locally, servers already on :8000/:3000 are reused,
// so a backend you started with ANTHROPIC_API_KEY set will make the spec fail its
// rules-only check; stop it first.
// E2E_WEB_URL / E2E_API_URL run a second copy beside servers you already have on
// :3000/:8000 (e.g. http://127.0.0.1:3100 and http://127.0.0.1:8100).
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
      env: { ANTHROPIC_API_KEY: "", CORS_ORIGINS: WEB, RT_PUBLIC_URL: WEB },
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
