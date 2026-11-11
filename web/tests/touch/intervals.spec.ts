import { expect, test, type Page } from "@playwright/test";

// Session 19: intervals within a piece, against ?mock=1 fixtures. Runs in the mobile projects
// (390px iPhone profile) — the editor is stacked rows specifically so it never needs sideways
// scrolling there, which the first test asserts directly.

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/workouts/6?mock=1");
  await expect(page.getByRole("heading", { name: "Pieces" })).toBeVisible();
});

async function openIntervalEditor(page: Page) {
  await page.getByRole("button", { name: "Add piece" }).click();
  await page.getByRole("button", { name: /^Intervals \(/ }).click();
  await expect(page.getByTestId("interval-editor")).toBeVisible();
}

test("4 x 500m quick-add makes four rows without sideways scrolling", async ({ page }) => {
  await openIntervalEditor(page);
  await page.getByRole("button", { name: /^Add 4 ×/ }).click();
  await expect(page.getByTestId("interval-row")).toHaveCount(4);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("edit, reorder, delete, then save and see work and rest reported separately", async ({ page }) => {
  await openIntervalEditor(page);
  await page.getByRole("button", { name: /^Add 4 ×/ }).click();
  await expect(page.getByTestId("interval-row")).toHaveCount(4);

  await page.getByLabel("Interval 2 distance (m)").fill("750");
  await page.getByRole("button", { name: "Move interval 2 up" }).click();
  await expect(page.getByLabel("Interval 1 distance (m)")).toHaveValue("750");
  await page.getByRole("button", { name: "Delete interval 4" }).click();
  await expect(page.getByTestId("interval-row")).toHaveCount(3);

  await page.getByRole("button", { name: "Save intervals" }).click();
  await expect(page.getByTestId("interval-editor")).toBeHidden(); // WorkoutDetail closes the dialog on save

  const table = page.getByTestId("interval-table");
  await expect(table).toBeVisible();
  // 750 + 500 + 500 work; rests after #1 and #2 only (the old #4's rest-free tail was deleted,
  // and the surviving last interval keeps the rest it was generated with).
  await expect(table).toContainText("1,750m");
  await expect(table.getByTestId("rest-row").first()).toContainText("rest 1:00");
});

test("an inconsistent interval is flagged, and can still be saved anyway", async ({ page }) => {
  await openIntervalEditor(page);
  await page.getByRole("button", { name: /^Add 4 ×/ }).click();
  await page.getByRole("button", { name: "More" }).first().click();
  await page.getByLabel("Avg HR").first().fill("150");
  await page.getByLabel("Max HR").first().fill("120");
  await page.getByRole("button", { name: "Save intervals" }).click();
  await expect(page.getByText("Max HR can't be below average HR.")).toBeVisible();
  await page.getByRole("button", { name: "Save anyway" }).click();
  await expect(page.getByTestId("interval-table")).toBeVisible();
});

test("an existing interval piece can be edited in place from its card", async ({ page }) => {
  await openIntervalEditor(page);
  await page.getByRole("button", { name: /^Add 4 ×/ }).click();
  await page.getByRole("button", { name: "Save intervals" }).click();
  await expect(page.getByTestId("interval-editor")).toBeHidden();
  await page.getByRole("button", { name: "Edit intervals" }).click();
  await page.getByRole("button", { name: "+ Add custom interval" }).click();
  await expect(page.getByTestId("interval-row")).toHaveCount(5);
  await page.getByTestId("interval-editor").locator("xpath=..").getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByTestId("interval-table").locator("tbody")).toHaveCount(5);
});
