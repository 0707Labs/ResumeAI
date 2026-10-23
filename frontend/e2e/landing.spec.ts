import { expect, test } from "@playwright/test";

// The public landing page, server-rendered against the real backend (invite-only by default).

test("landing: server-rendered sections, invite-only sign up, footer", async ({ page, request }) => {
  const config = await (await request.get("/api/auth/config")).json();
  test.skip(config.invite_only === false, "the backend here runs with RT_INVITE_ONLY off");

  // The HTML itself carries the content (no client rendering needed for crawlers).
  const html = await (await request.get("/")).text();
  expect(html).toContain("Tailor your resume to any job, without ever inventing experience");
  expect(html).toContain('"@type":"FAQPage"');

  const hydrationErrors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error" && /hydrat/i.test(m.text())) hydrationErrors.push(m.text()); });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Tailor your resume to any job, without ever inventing experience",
  );
  for (const name of ["From job post to tailored resume in minutes", "Only what you've actually done",
    "A sample before and after", "Simple, one-time prices", "Good to know"]) {
    await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  }
  // The workspace's step bar doesn't belong here.
  await expect(page.getByRole("navigation", { name: "Progress" })).toHaveCount(0);

  const footer = page.getByRole("contentinfo");
  await expect(footer).toContainText("A product of 0707Labs, MealOBox Foodtech Pvt Ltd");
  for (const name of ["Terms of Service", "Privacy Policy", "Refund Policy", "Grievance redressal"]) {
    await expect(footer.getByRole("link", { name })).toBeVisible();
  }

  await expect(page.getByRole("banner").getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/signin");
  await page.getByRole("banner").getByRole("button", { name: "Sign up" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Resume Tailor is invite-only for now" })).toBeVisible();
  await dialog.getByLabel(/Invite code/).fill("ABCD-EFGH-JKLM");
  await dialog.getByRole("button", { name: "Continue to sign up" }).click();
  await expect(page).toHaveURL(/\/signup$/);
  expect(await page.evaluate(() => sessionStorage.getItem("rt:invite-code"))).toBe("ABCD-EFGH-JKLM");
  expect(hydrationErrors).toEqual([]);
});

test("landing: legal pages render and the page fits a phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  // The section links live in a menu on phones.
  const banner = page.getByRole("banner");
  await expect(banner.getByRole("link", { name: "FAQ" })).toBeHidden();
  await banner.getByRole("button", { name: "Open menu" }).click();
  await banner.locator("#site-menu").getByRole("link", { name: "FAQ" }).click();
  await expect(page).toHaveURL(/#faq$/);
  await expect(banner.locator("#site-menu")).toHaveCount(0);

  for (const [path, title] of [["/legal/terms", "Terms of Service"], ["/legal/privacy", "Privacy Policy"],
    ["/legal/refunds", "Refund Policy"], ["/legal/grievance", "Grievance redressal"]]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
  }
});
