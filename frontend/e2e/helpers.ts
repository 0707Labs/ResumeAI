import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { type APIRequestContext, expect, type Page } from "@playwright/test";

// Shared by the specs that need real accounts: invites and consent notices come from
// the backend's admin CLI, magic links from its dev outbox (backend/.dev-outbox).

const BACKEND = resolve(__dirname, "../../backend");
const OUTBOX = join(BACKEND, ".dev-outbox");
export const API = process.env.E2E_API_URL ?? "http://localhost:8000";

export function cli(...args: string[]): string {
  return execFileSync(join(BACKEND, ".venv/bin/python"), ["-m", "app.auth.cli", ...args], {
    cwd: BACKEND, encoding: "utf8",
  }).trim();
}

/** Publish any missing notice so sign-up and the waitlist are open. */
export async function ensureNotices(request: APIRequestContext) {
  const have = new Set((await (await request.get(`${API}/api/auth/notices`)).json()).map((n: { purpose: string }) => n.purpose));
  const body = join(mkdtempSync(join(tmpdir(), "rt-e2e-")), "notice.txt");
  writeFileSync(body, "End-to-end test notice.\n");
  for (const purpose of ["service", "age_18_plus", "research", "waitlist"]) {
    if (!have.has(purpose)) cli("publish-notice", purpose, "e2e-v1", `/legal/${purpose}`, "--body-file", body);
  }
}

/** The newest magic link emailed to `to`. */
export async function linkFor(to: string): Promise<string> {
  let link = "";
  await expect.poll(() => {
    const mails = readdirSync(OUTBOX).sort().reverse().map((f) => readFileSync(join(OUTBOX, f), "utf8"));
    const mail = mails.find((m) => m.startsWith(`To: ${to}\n`));
    link = /(http\S+#token=\S+)/.exec(mail ?? "")?.[1] ?? "";
    return link;
  }, { message: `no email for ${to}` }).not.toBe("");
  return link;
}

export const uniqueEmail = (tag: string) => `e2e-${tag}-${Date.now()}@example.com`;

/** A brand-new account, signed in on `page` (email link, invite, consent). */
export async function signUp(page: Page, tag: string): Promise<string> {
  const email = uniqueEmail(tag);
  const code = cli("create-invite", "--note", `e2e ${tag}`);
  await page.goto("/signup");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Email me a sign-in link" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Check your email" })).toContainText(email);
  await page.goto(await linkFor(email));
  await expect(page).toHaveURL(/\/signup\/(invite|consent)$/);
  if (page.url().endsWith("/signup/invite")) {
    await page.getByLabel(/Invite code/).fill(code);
    await page.getByRole("button", { name: "Continue" }).click();
  }
  await expect(page).toHaveURL(/\/signup\/consent$/);
  await page.getByRole("checkbox", { name: /18 years of age or older/ }).check();
  await page.getByRole("checkbox", { name: /Terms of Service and Privacy Policy/ }).check();
  await page.getByRole("button", { name: "Create my account" }).click();
  await expect(page).toHaveURL(/\/app$/);
  return email;
}
