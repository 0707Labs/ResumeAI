import { expect, test } from "@playwright/test";

import { ensureNotices, signUp } from "./helpers";

// Past this month's free tailorings, with no pass or credits, Analyze opens the pricing
// dialog instead of starting a run.

test("free tailorings run out: the pricing dialog, and no new run", async ({ page, request }) => {
  await ensureNotices(request);
  await signUp(page, "limits");
  await page.goto("/app");
  await page.getByRole("button", { name: "No resume handy? Try a sample" }).click();
  await expect(page.getByText("Up to date")).toBeVisible();
  for (let i = 0; i < 2; i++) {
    await page.getByRole("button", { name: "Analyze" }).click();
    await expect(page).toHaveURL(/\/app\/analysis$/);
    await page.goto("/app");
  }
  await expect(page.getByTestId("allowance")).toContainText("used this month's 2 free tailorings");
  await page.getByRole("button", { name: "Analyze" }).click();
  const dialog = page.getByRole("dialog", { name: "You've used this month's free tailorings" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Credits are only spent when you download");
  await expect(page).toHaveURL(/\/app$/);
});
