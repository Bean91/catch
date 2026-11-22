import { expect, test, type Page } from "@playwright/test";

// Session 33: merging workouts, against ?mock=1 (the mock has one erg session recorded in two parts this morning: "Steady state 30'"
// and "Steady state 20'", 40 minutes apart). Runs in both mobile projects at 390px.

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/workouts?mock=1");
  await page.getByRole("button", { name: "Select", exact: true }).click();
});

// The two parts are the oldest erg sessions in the mock, so the list loads further pages as it scrolls.
async function revealParts(page: Page) {
  await page.getByRole("tab", { name: "Erg" }).click();
  const target = page.getByLabel("Select Steady state 20'");
  for (let i = 0; i < 12 && !(await target.isVisible()); i++) {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(250);
  }
}

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("merge two parts of one session: preview, confirm, see it merged, undo", async ({ page }) => {
  await revealParts(page);
  await expect(page.getByTestId("merge-selected")).toHaveCount(0); // needs two selected
  await page.getByLabel("Select Steady state 30'").check();
  await page.getByLabel("Select Steady state 20'").check();
  await page.getByTestId("merge-selected").click();

  const sheet = page.getByTestId("merge-sheet");
  await expect(sheet).toBeVisible();
  await expect(sheet.getByTestId("merge-item-900")).toContainText("30:00");
  await expect(sheet.getByTestId("merge-item-901")).toContainText("20:00");
  const result = sheet.getByTestId("merge-result");
  await expect(result).toContainText("50:00"); // 30 + 20 minutes of moving time — the 10-minute gap isn't counted
  await expect(result).toContainText("12,000");
  await expect(result).toContainText("150 bpm"); // (142 × 30 + 163 × 20) / 50 — weighted, not (142 + 163) / 2
  await expect(sheet.getByText("kept as the merged workout")).toBeVisible();
  await noSidewaysScroll(page);

  // The confirm button must sit clear of the bottom nav (z-30 sheet rule).
  const button = sheet.getByRole("button", { name: "Merge these workouts" });
  await button.scrollIntoViewIfNeeded();
  await button.click();

  await expect(page).toHaveURL(/\/workouts\/900/);
  const merged = page.getByTestId("merged-workout");
  await expect(merged).toContainText("Merged from 2 workouts");
  await merged.getByRole("button", { name: "Undo merge" }).click();
  await expect(page.getByRole("group", { name: "Confirm undo merge" })).toBeVisible();
  await page.getByRole("group", { name: "Confirm undo merge" }).getByRole("button", { name: "Undo merge" }).click();
  await expect(page.getByTestId("merged-workout")).toHaveCount(0);
});

test("workouts that can't be merged say why, and offer no merge button", async ({ page }) => {
  await revealParts(page);
  await page.getByLabel("Select Steady state 30'").check();
  await page.getByRole("tab", { name: "Strength" }).click();
  await page.getByLabel(/^Select Strength/).first().check();
  await page.getByTestId("merge-selected").click();
  const sheet = page.getByTestId("merge-sheet");
  const reasons = sheet.getByTestId("merge-reasons");
  await expect(reasons).toContainText("different sports");
  await expect(sheet.getByRole("button", { name: "Merge these workouts" })).toHaveCount(0);
  await sheet.getByRole("button", { name: "Close" }).click();
  await expect(sheet).toBeHidden();
});
