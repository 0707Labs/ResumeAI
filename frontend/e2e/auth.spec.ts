import { expect, test } from "@playwright/test";

import { API, cli, ensureNotices, linkFor, uniqueEmail } from "./helpers";

// Sign-up and sign-in against the real backend and its Postgres database.
// Google/GitHub can't be driven here without real apps; the backend tests mock them.

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

  await expect(page).toHaveURL(/\/app\/welcome$/);  // first sign-in: the welcome steps
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.locator("#account-menu").getByRole("link", { name: "Profile" }).click();
  await expect(page.getByLabel(/how you sign in/)).toHaveValue(email);  // Profile > Personal
  await expect(page.getByRole("button", { name: /Disconnect Email link/ })).toBeDisabled();
  await expect(page.getByText(/only way to sign in/)).toBeVisible();

  await page.getByRole("button", { name: "Account menu" }).click();
  await page.locator("#account-menu").getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/$/);  // back to the landing page, signed out
  await expect(page.getByRole("banner").getByRole("link", { name: "Sign in" })).toBeVisible();
});

test("no invite: no account, and the waitlist is pre-filled", async ({ page, request }) => {
  const email = uniqueEmail("waitlist");
  await page.goto("/signin");
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
  await page.goto("/signin");
  await expect(page.getByText("Continue with Google")).toBeVisible();
  await expect(page.getByRole("link", { name: "Continue with Google" })).toHaveCount(0);
  await page.goto("/api/auth/google/start");
  await expect(page).toHaveURL(/\/signin\?error=provider_unavailable$/);
  await expect(page.getByRole("alert").filter({ hasText: "Provider unavailable" })).toBeVisible();
});
