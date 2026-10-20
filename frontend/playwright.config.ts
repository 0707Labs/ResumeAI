import { defineConfig, devices } from "@playwright/test";

// End-to-end happy path against the real FastAPI backend in rules-only mode.
// Run with `npm run test:e2e`. Locally, servers already on :8000/:3000 are reused,
// so a backend you started with ANTHROPIC_API_KEY set will make the spec fail its
// rules-only check; stop it first.
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
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000",
      cwd: "..",
      url: "http://localhost:8000/health",
      // Empty key = rules only: deterministic output, no network calls to Anthropic.
      env: { ANTHROPIC_API_KEY: "", CORS_ORIGINS: "http://localhost:3000" },
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:3000",
      env: { NEXT_PUBLIC_API_URL: "http://localhost:8000" },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
