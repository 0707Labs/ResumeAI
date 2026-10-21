import { expect, test } from "@playwright/test";

import { ensureNotices, linkFor, signUp } from "./helpers";

// The workspace needs a signed-in user: signed-out visitors go to /signin and come back
// to the page they asked for. The backend's own checks are covered by pytest.

test.beforeAll(async ({ request }) => {
  await ensureNotices(request);
});

test("signed out: the workspace sends you to sign in, remembering where you were going", async ({ page }) => {
  for (const path of ["/app", "/review", "/export"]) {
    await page.goto(path);
    await expect(page).toHaveURL(new RegExp(`/signin\\?next=${encodeURIComponent(path)}$`));
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  }
  // Old links still work.
  await page.goto("/login");
  await expect(page).toHaveURL(/\/signin$/);
});

test("a stale session cookie doesn't get into the workspace", async ({ page, context, baseURL }) => {
  await context.addCookies([{ name: "rt_session", value: "not-a-real-session", url: baseURL! }]);
  await page.goto("/app");
  await expect(page).toHaveURL(/\/signin\?next=%2Fapp$/);
});

// Magic links are limited to 5 per 15 minutes per IP, so this spec sends only two.
test("signed in: sign-in pages skip ahead; email sign-in returns to the page asked for", async ({ page, browser, baseURL }) => {
  const email = await signUp(page, "return");
  await page.goto("/signin");
  await expect(page).toHaveURL(/\/app$/);
  await page.goto("/signup");
  await expect(page).toHaveURL(/\/app$/);

  // A fresh browser, signed out, asks for /review.
  const other = await browser.newContext({ baseURL });
  const tab = await other.newPage();
  await tab.goto("/review");
  await expect(tab).toHaveURL(/\/signin\?next=%2Freview$/);
  await tab.getByLabel("Email").fill(email);
  await tab.getByRole("button", { name: "Email me a sign-in link" }).click();
  await expect(tab.getByRole("status").filter({ hasText: "Check your email" })).toBeVisible();

  // The emailed link opens in a new tab of the same browser.
  const linkTab = await other.newPage();
  await linkTab.goto(await linkFor(email));
  await expect(linkTab).toHaveURL(/\/review$/);
  await other.close();
});
