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
  // A new account lands on the first-login steps; the specs skip them.
  await expect(page).toHaveURL(/\/app\/welcome$/);
  await page.getByRole("button", { name: "Skip setup" }).click();
  await expect(page).toHaveURL(/\/app\/dashboard$/);
  return email;
}

/** Grant credits to the account signed in on `page`, with the billing admin CLI (what a
 * verified purchase webhook does through the same ledger). */
export async function giveCredits(page: Page, n: number) {
  const me = await (await page.request.get("/api/me")).json();
  execFileSync(join(BACKEND, ".venv/bin/python"),
    ["-m", "app.billing.cli", "adjust-credits", me.id, String(n), "--note", "e2e"], { cwd: BACKEND, encoding: "utf8" });
}

// --- payments in test mode --------------------------------------------------------------------
// Dodo's hosted checkout can't run here, so the checkout call is answered in the browser:
// it records the payment row exactly as POST /api/billing/checkout would (via Python) and
// sends the buyer straight to our /billing/success page. Everything after that is real:
// a Standard-Webhooks-signed payment.succeeded (scripts/dodo_send_webhook.py, the same
// tool as for local test mode) goes through signature checks, idempotency and the ledger.

/** Shared with the backend started by playwright.config.ts (DODO_WEBHOOK_SECRET). */
export const E2E_WEBHOOK_SECRET = "whsec_" + Buffer.from("e2e-webhook-secret-32-bytes-long").toString("base64");

function python(code: string, ...args: string[]): string {
  return execFileSync(join(BACKEND, ".venv/bin/python"), ["-c", code, ...args], { cwd: BACKEND, encoding: "utf8" }).trim();
}

const CREATE_PAYMENT = `
import json, sys, uuid
from sqlalchemy import create_engine, text
from app.billing.config import get_billing_config
from app.config import get_settings
user_id, product_key = sys.argv[1], sys.argv[2]
product = get_billing_config().products[product_key]
snapshot = {"catalog_version": 1, "provider_product_id": "pdt_e2e_" + product_key, "credits": product.credits,
            "pass_days": product.pass_days, "fair_use_cap": product.fair_use_cap, "name": product.name}
engine = create_engine(get_settings().database_url)
with engine.begin() as conn:
    print(conn.execute(text(
        "INSERT INTO payments (user_id, provider, mode, product_key, kind, snapshot, idempotency_key,"
        " provider_checkout_id) VALUES (:u, 'dodo', 'test', :p, :k, CAST(:s AS jsonb), :i, :c) RETURNING id"),
        {"u": user_id, "p": product_key, "k": product.kind, "s": json.dumps(snapshot), "i": uuid.uuid4().hex,
         "c": "cks_e2e_" + uuid.uuid4().hex[:12]}).scalar_one())
`;

const FAKE_CHECKOUT = "https://checkout.e2e.invalid/session"; // must be https, like Dodo's

/** Make the plans buyable in this page and answer checkouts as described above. Returns
 * the payment ids created, in order. */
export async function fakeCheckout(page: Page): Promise<string[]> {
  const created: string[] = [];
  await page.route("**/api/billing/plans", async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.plans = body.plans.map((p: { available: boolean }) => ({ ...p, available: true }));
    await route.fulfill({ response: res, json: body });
  });
  await page.route("**/api/billing/checkout", async (route) => {
    const me = await (await page.request.get("/api/me")).json();
    const productKey = JSON.parse(route.request().postData() ?? "{}").product_key;
    const paymentId = python(CREATE_PAYMENT, me.id, productKey);
    created.push(paymentId);
    await route.fulfill({ json: { payment_id: paymentId, checkout_url: `${FAKE_CHECKOUT}/${paymentId}` } });
  });
  // The "hosted checkout" sends the buyer straight back, as Dodo's return URL would.
  await page.route(`${FAKE_CHECKOUT}/**`, async (route) => {
    const paymentId = new URL(route.request().url()).pathname.split("/").pop();
    const origin = new URL(page.url()).origin;
    await route.fulfill({ status: 302, headers: { location: `${origin}/billing/success?payment=${paymentId}` } });
  });
  return created;
}

/** Dodo's signed payment.succeeded for that payment, delivered to the backend's webhook. */
export function payWebhook(paymentId: string) {
  execFileSync(join(BACKEND, ".venv/bin/python"),
    ["scripts/dodo_send_webhook.py", "payment.succeeded", "--payment-row", paymentId,
      "--url", `${API}/api/billing/webhooks/dodo`],
    { cwd: BACKEND, encoding: "utf8", env: { ...process.env, DODO_WEBHOOK_SECRET: E2E_WEBHOOK_SECRET, DODO_ENVIRONMENT: "test" } });
}
