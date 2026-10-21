import { readFile } from "node:fs/promises";

import { expect, type Locator, type Page, test } from "@playwright/test";

import { signUp } from "./helpers";

// One full pass through the app against the real backend in rules-only mode
// (no ANTHROPIC_API_KEY), so every tailored bullet starts out unchanged and the
// only edits are the two made here by hand. Downloading needs an account (it's what
// pays), so this signs up first; the download uses the month's first free download.
// Needs Postgres, like auth.spec.ts.

const ANSWER = "At Acme Retail I built dbt models that feed the weekly SQL extracts.";
const CITED = "Cut weekly reporting time by 30% by automating SQL extracts with dbt models";
const FABRICATED = "Built 45 recurring reports in Snowflake for regional operations leads";

const bulletWith = (page: Page, text: string) => page.getByTestId(/^bullet-/).filter({ hasText: text });

async function editBullet(bullet: Locator, text: string, citeAnswer?: RegExp) {
  await bullet.getByRole("button", { name: "Edit manually" }).click();
  await bullet.getByLabel("Your wording").fill(text);
  if (citeAnswer) await bullet.getByRole("checkbox", { name: citeAnswer }).check();
  await bullet.getByRole("button", { name: "Save and re-check" }).click();
  await expect(bullet.getByRole("button", { name: "Save and re-check" })).toHaveCount(0);
}

async function ringValue(page: Page, label: RegExp): Promise<number> {
  const aria = await page.getByRole("img", { name: label }).getAttribute("aria-label");
  const m = /: ([\d.]+) out of 100$/.exec(aria ?? "");
  if (!m) throw new Error(`No score in ring label: ${aria}`);
  return Number(m[1]);
}

test("sample resume: answer, review, score, mentor, export", async ({ page, request }) => {
  const health = await (await request.get("http://localhost:8000/health")).json();
  expect(health.llm_configured, "backend must run without ANTHROPIC_API_KEY").toBe(false);

  // 0. A new account, signed in.
  await signUp(page, request, "happy");

  // 1. Input
  await page.goto("/");
  await page.getByRole("button", { name: "No resume handy? Try a sample" }).click();
  await expect(page.getByText("Up to date")).toBeVisible();
  await page.getByRole("button", { name: "Analyze" }).click();
  await expect(page).toHaveURL(/\/analysis$/);

  // 2. Gaps and questions: first missing question Yes, second No, third Skip.
  const questions = page.locator('section[aria-labelledby="group-missing"] fieldset');
  await expect(questions).toHaveCount(3);
  const [yes, no, skip] = [questions.nth(0), questions.nth(1), questions.nth(2)];
  await expect(yes).toContainText("dbt or Airflow");
  await yes.locator("label", { hasText: "Yes, I'll describe it" }).click();
  await yes.getByLabel("Where and how did you use it?").fill(ANSWER);
  await no.locator("label", { hasText: /^No$/ }).click();
  await skip.locator("label", { hasText: "Skip" }).click();
  await expect(page.locator("#questions-progress")).toContainText("3 of 3");
  await page.getByRole("button", { name: "Continue to tailoring" }).click();
  await expect(page).toHaveURL(/\/review$/);

  // 3. Review: cite the confirmed answer in an unchanged bullet; it verifies.
  await expect(page.getByRole("heading", { name: "Review each change" })).toBeVisible();
  const bar = page.getByTestId("review-bar");
  const cited = bulletWith(page, "Cut weekly reporting time");
  await expect(cited).toContainText("No change");
  await editBullet(cited, CITED, /q2/);
  await expect(cited.getByTestId("tailored")).toContainText("dbt models");
  await expect(cited.getByText("Verified")).toBeVisible();
  await cited.getByRole("button", { name: "Approve" }).click();
  await expect(cited.getByRole("button", { name: "Approved" })).toHaveAttribute("aria-pressed", "true");
  await expect(bar).toContainText("Ready to export");

  // A fabricated tool and number get flagged and can't be approved.
  const fabricated = bulletWith(page, "recurring reports for regional operations leads");
  await editBullet(fabricated, FABRICATED);
  await expect(fabricated.getByText("Needs your check")).toBeVisible();
  await expect(fabricated.getByText("snowflake", { exact: true })).toBeVisible();
  await expect(fabricated.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
  await expect(bar).toContainText("1 flagged change needs your decision before export");
  await fabricated.getByRole("button", { name: "Reject (keep original)" }).click();
  await expect(fabricated.getByRole("button", { name: "Keeping original" })).toBeVisible();
  await expect(bar).toContainText("Ready to export");

  // 4. Score: the approved, answer-backed edit raises the estimate.
  await page.getByRole("link", { name: "See your score" }).click();
  await expect(page).toHaveURL(/\/score$/);
  await expect(page.getByText("Estimate only. Real ATS systems vary.")).toBeVisible();
  const afterRing = /^With your 1 approved change:/;
  await expect(page.getByRole("img", { name: afterRing })).toBeVisible();
  await expect(page.getByText(/^\+[\d.]+ points$/)).toBeVisible();
  const before = await ringValue(page, /^Your original resume:/);
  const after = await ringValue(page, afterRing);
  expect(after).toBeGreaterThan(before);

  // 5. Mentor: verdict renders; tick one plan task.
  await page.getByRole("link", { name: "Talk it through with the mentor" }).click();
  await expect(page).toHaveURL(/\/mentor$/);
  await expect(page.getByTestId("verdict")).toContainText("Should you apply?");
  const task = page.locator('input[type="checkbox"][id^="plan-"]').first();
  await task.check();
  await expect(task).toBeChecked();
  await expect(page.getByText(/^1 of \d+$/)).toBeVisible();

  // 6. Export: preview marks only the approved line; DOCX downloads as a zip.
  await page.getByRole("link", { name: "Export your resume" }).click();
  await expect(page).toHaveURL(/\/export$/);
  const changed = page.getByTestId("resume-document").locator('[data-changed="true"]');
  await expect(changed).toHaveCount(1);
  await expect(changed).toContainText(CITED);

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download DOCX" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("Asha_Rao_tailored.docx");
  const file = await readFile(await download.path());
  expect(file.subarray(0, 4).toString("latin1")).toBe("PK\x03\x04");
  expect(file.includes("word/document.xml")).toBe(true);
});
