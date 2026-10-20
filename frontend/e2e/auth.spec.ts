import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { type APIRequestContext, expect, test } from "@playwright/test";

// Sign-up and sign-in against the real backend and its Postgres database.
// Invites and consent notices are created with the backend's admin CLI; magic
// links are read from the dev outbox (backend/.dev-outbox), as a developer would.
// Google/GitHub can't be driven here without real apps; the backend tests mock them.

const BACKEND = resolve(__dirname, "../../backend");
const OUTBOX = join(BACKEND, ".dev-outbox");
const API = "http://localhost:8000";

function cli(...args: string[]): string {
  return execFileSync(join(BACKEND, ".venv/bin/python"), ["-m", "app.auth.cli", ...args], {
    cwd: BACKEND, encoding: "utf8",
  }).trim();
}

/** Publish any missing notice so sign-up and the waitlist are open. */
async function ensureNotices(request: APIRequestContext) {
  const have = new Set((await (await request.get(`${API}/api/auth/notices`)).json()).map((n: { purpose: string }) => n.purpose));
  const body = join(mkdtempSync(join(tmpdir(), "rt-e2e-")), "notice.txt");
  writeFileSync(body, "End-to-end test notice.\n");
  for (const purpose of ["service", "age_18_plus", "research", "waitlist"]) {
    if (!have.has(purpose)) cli("publish-notice", purpose, "e2e-v1", `/legal/${purpose}`, "--body-file", body);
  }
}

/** The newest magic link emailed to `to`. */
async function linkFor(to: string): Promise<string> {
  let link = "";
  await expect.poll(() => {
    const mails = readdirSync(OUTBOX).sort().reverse().map((f) => readFileSync(join(OUTBOX, f), "utf8"));
    const mail = mails.find((m) => m.startsWith(`To: ${to}\n`));
    link = /(http\S+#token=\S+)/.exec(mail ?? "")?.[1] ?? "";
    return link;
  }, { message: `no email for ${to}` }).not.toBe("");
  return link;
}

const uniqueEmail = (tag: string) => `e2e-${tag}-${Date.now()}@example.com`;

test.beforeAll(async ({ request }) => {
  await ensureNotices(request);
});

test("invite, consent, signed in; last sign-in method can't be removed", async ({ page }) => {
  const email = uniqueEmail("invite");
  const code = cli("create-invite", "--note", "e2e");

  await page.goto("/signup");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Email me a sign-in link" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Check your email" })).toContainText(email);

  await page.goto(await linkFor(email));
  await expect(page).toHaveURL(/\/signup\/invite$/);
  await expect(page.getByText(email)).toBeVisible();
  await page.getByLabel(/Invite code/).fill(code);
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page).toHaveURL(/\/signup\/consent$/);
  const create = page.getByRole("button", { name: "Create my account" });
  await expect(create).toBeDisabled();
  await expect(page.getByRole("checkbox", { name: /Help improve the product/ })).not.toBeChecked();
  await page.getByRole("checkbox", { name: /18 years of age or older/ }).check();
  await page.getByRole("checkbox", { name: /Terms of Service and Privacy Policy/ }).check();
  await create.click();

  await expect(page).toHaveURL("http://localhost:3000/");
  await page.getByRole("link", { name: "Account" }).click();
  await expect(page.getByText(`Signed in as ${email}`)).toBeVisible();
  await expect(page.getByRole("button", { name: /Disconnect Email link/ })).toBeDisabled();
  await expect(page.getByText(/only way to sign in/)).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
});

test("no invite: no account, and the waitlist is pre-filled", async ({ page, request }) => {
  const email = uniqueEmail("waitlist");
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Email me a sign-in link" }).click();
  await page.goto(await linkFor(email));
  await expect(page).toHaveURL(/\/signup\/invite$/);

  await page.getByLabel(/Invite code/).fill("NOPE-NOPE-NOPE");
  await page.getByRole("button", { name: "Continue" }).click();
  // (Next's route announcer is also role=alert, so match ours by its text.)
  const alert = page.getByRole("alert").filter({ hasText: "No invite found for this account" });
  await expect(alert).toBeVisible();
  expect((await request.get(`${API}/api/me`)).status()).toBe(401);

  await alert.getByRole("link", { name: "Join the waitlist" }).click();
  await expect(page).toHaveURL(/\/waitlist$/);
  await expect(page.getByLabel("Email")).toHaveValue(email);
  await expect(page.url()).not.toContain(encodeURIComponent(email)); // never in the URL
  await page.getByRole("checkbox", { name: /18 years/ }).check();
  await page.getByRole("button", { name: "Join the waitlist" }).click();
  await expect(page.getByText("You're on the list")).toBeVisible();
});

test("an unconfigured provider says so", async ({ page, request }) => {
  const providers = await (await request.get(`${API}/api/auth/providers`)).json();
  test.skip(providers.google, "Google sign-in is configured on this backend");
  await page.goto("/login");
  await expect(page.getByText("Continue with Google")).toBeVisible();
  await expect(page.getByRole("link", { name: "Continue with Google" })).toHaveCount(0);
  await page.goto("/api/auth/google/start");
  await expect(page).toHaveURL(/\/login\?error=provider_unavailable$/);
  await expect(page.getByRole("alert").filter({ hasText: "Provider unavailable" })).toBeVisible();
});
