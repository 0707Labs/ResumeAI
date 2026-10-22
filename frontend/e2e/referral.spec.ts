import { expect, test } from "@playwright/test";

import { ensureNotices, linkFor, signUp, uniqueEmail } from "./helpers";

// A referrer shares their link; a friend opens it, signs up (invite-only: the link is the
// invite), and finishes a first tailoring; the referrer's header shows the new credit and
// "Your friend joined. +1 credit". Defaults: trigger on_first_tailoring, 1 credit.

test("referral: link → friend joins with it → first tailoring → referrer is credited", async ({ page, browser, baseURL, request }) => {
  await ensureNotices(request);
  await signUp(page, "referrer");
  await page.goto("/account/referrals");
  const link = (await page.getByTestId("referral-link").textContent())!.trim();
  expect(link).toMatch(/\/\?ref=[A-Z2-9]{8}$/);
  await expect(page.getByText(/works as an invite: 5 left/)).toBeVisible();

  // The friend, in their own browser.
  const friendContext = await browser.newContext({ baseURL });
  const friend = await friendContext.newPage();
  await friend.goto(link);
  await expect.poll(async () => (await friendContext.cookies()).find((c) => c.name === "rt_ref")?.value)
    .toBe(link.split("ref=")[1]);
  const email = uniqueEmail("friend");
  await friend.goto("/signup");
  await friend.getByLabel("Email").fill(email);
  await friend.getByRole("button", { name: "Email me a sign-in link" }).click();
  await friend.goto(await linkFor(email));
  await expect(friend).toHaveURL(/\/signup\/invite$/);
  await friend.getByRole("button", { name: "Use my friend's invite" }).click();
  await expect(friend).toHaveURL(/\/signup\/consent$/);
  await friend.getByRole("checkbox", { name: /18 years of age or older/ }).check();
  await friend.getByRole("checkbox", { name: /Terms of Service and Privacy Policy/ }).check();
  await friend.getByRole("button", { name: "Create my account" }).click();
  await expect(friend).toHaveURL(/\/app$/);

  // Joined, not yet rewarded (the trigger is the first tailoring).
  await page.reload();
  await expect(page.getByText(/Waiting for their first tailoring/)).toBeVisible();
  await expect(page.getByText(/works as an invite: 4 left/)).toBeVisible();

  // The friend's first tailoring.
  await friend.getByRole("button", { name: "No resume handy? Try a sample" }).click();
  await expect(friend.getByText("Up to date")).toBeVisible();
  await friend.getByRole("button", { name: "Analyze" }).click();
  await expect(friend).toHaveURL(/\/app\/analysis$/);
  const questions = friend.locator('section[aria-labelledby="group-missing"] fieldset');
  for (let i = 0; i < await questions.count(); i++) await questions.nth(i).locator("label", { hasText: "Skip" }).click();
  await friend.getByRole("button", { name: "Continue to tailoring" }).click();
  await expect(friend.getByRole("heading", { name: "Review each change" })).toBeVisible();

  // The referrer sees it live: the header balance and a one-time notice.
  await page.goto("/app");
  await expect(page.getByTestId("credits-balance")).toHaveText("1 credit");
  await expect(page.getByRole("status").filter({ hasText: "Your friend joined. +1 credit" })).toBeVisible();
  await page.goto("/account/referrals");
  await expect(page.getByText(/Rewarded · \+1 credit/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: "Your friend joined" })).toHaveCount(0); // shown once
  await friendContext.close();
});
