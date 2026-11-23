import { expect, test, type Page } from "@playwright/test";

// Session 36 against ?mock=1, in both mobile projects at 390px: the Performance Lab, goals, planned-vs-done, the linked-chart note,
// "About this data", workout search, the duplicate comparison, load history, coach ref links and per-category exports.

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("performance lab: records with labels and history, progression, like-for-like tables, 2k inputs", async ({ page }) => {
  await page.goto("/lab?mock=1");
  const records = page.getByTestId("records-card");
  await expect(records).toContainText("2,000 m");
  await expect(records).toContainText("6:52.3");
  await expect(records.getByText("Test").first()).toBeVisible();
  await records.getByRole("button", { name: /History \(2\)/ }).click();
  await expect(records.getByTestId("record-history")).toContainText("6:58.4");
  await records.getByRole("tab", { name: "Power" }).click();
  await expect(records.getByTestId("records-power")).toContainText("5 min or longer");

  await expect(page.getByTestId("progression-card")).toContainText("new best");
  await expect(page.getByTestId("hr-workload-card")).toContainText("4 bpm lower");
  await expect(page.getByTestId("hr-workload-card")).toContainText("—"); // a side with too little data is a dash, never a number
  await expect(page.getByTestId("split-rate-card")).toContainText("1.5 s faster");
  await expect(page.getByTestId("estimate-2k-card")).toContainText("Implies");
  await expect(page.getByTestId("estimate-2k-card")).toContainText("never a result");
  await noSidewaysScroll(page);
});

test("goals: weekly goal reads as weeks reached with no catch-up; add and finish a goal", async ({ page }) => {
  await page.goto("/goals?mock=1");
  await expect(page.getByTestId("active-goals")).toContainText("2 of 3 finished weeks reached it");
  await expect(page.getByText("there's nothing to make up on any one day")).toBeVisible();
  await expect(page.getByTestId("goal-card").filter({ hasText: /streak|missed|behind/i })).toHaveCount(0);
  await expect(page.getByTestId("goal-history")).toContainText("Learn to row square blade");

  await page.getByTestId("add-goal").click();
  const sheet = page.getByTestId("goal-sheet");
  await sheet.getByLabel("Kind of goal").selectOption("workout_count");
  await sheet.getByTestId("goal-target").fill("12");
  const save = sheet.getByTestId("save-goal");
  await save.scrollIntoViewIfNeeded();
  await save.click();
  await expect(sheet).toHaveCount(0);
  const card = page.getByTestId("goal-card").filter({ hasText: "New goal" });
  await card.getByRole("button", { name: "Mark done" }).click();
  await expect(page.getByTestId("goal-history")).toContainText("New goal");
  await noSidewaysScroll(page);
});

test("workout detail: planned and done, linked-chart note, about this data", async ({ page }) => {
  await page.goto("/workouts/11?mock=1");
  const planned = page.getByTestId("planned-and-done");
  await expect(planned).toContainText("✓ in range");
  await expect(planned).toContainText("Warm-up");
  await expect(planned).not.toContainText(/missed|behind|failed/i);

  await page.goto("/workouts/1?mock=1");
  const about = page.getByTestId("about-this-data");
  await about.getByText("About this data").click();
  await expect(about).toContainText("worked out (time ÷ distance)");
  await expect(about).toContainText("Heart rate present for 99%");
  await noSidewaysScroll(page);
});

test("workouts search: no match says so", async ({ page }) => {
  await page.goto("/workouts?mock=1");
  await page.getByTestId("workout-search").fill("zzzz-nothing");
  await expect(page.getByText("Nothing matches that search.")).toBeVisible();
  await noSidewaysScroll(page);
});

test("duplicates: compare before merging, each merged figure names its source", async ({ page }) => {
  await page.goto("/workouts/duplicates?mock=1");
  const pair = page.getByTestId("duplicate-pair").first();
  await pair.getByRole("button", { name: "Compare and merge…" }).click();
  const review = pair.getByTestId("merge-review");
  await expect(review).toContainText("If merged");
  await expect(review).toContainText("from Concept2");
  await expect(review.getByTestId("confirm-merge")).toBeVisible();
  await noSidewaysScroll(page);
});

test("trends: load and volume, monotony explained, recent against baseline", async ({ page }) => {
  await page.goto("/trends?mock=1");
  const card = page.getByTestId("load-history");
  await card.scrollIntoViewIfNeeded();
  await expect(card).toContainText("Training monotony each week");
  await expect(card).toContainText("Last 4 weeks");
  await expect(card).toContainText("+12%");
  await noSidewaysScroll(page);
});

test("coach: a cited workout becomes a link, other text stays text", async ({ page }) => {
  await page.goto("/coach?mock=1");
  await page.getByPlaceholder("Ask your coach…").fill("How did my last erg go?");
  await page.getByRole("button", { name: "Send" }).click();
  const link = page.getByTestId("coach-ref").first();
  await expect(link).toHaveAttribute("href", "/workouts/1");
  await link.click();
  await expect(page).toHaveURL(/\/workouts\/1/);
});

test("privacy: one download row per category", async ({ page }) => {
  await page.goto("/settings/privacy?mock=1");
  const rows = page.getByTestId("category-exports").getByRole("listitem");
  await expect(rows).toHaveCount(7);
  await expect(rows.first()).toContainText("Workouts");
  await noSidewaysScroll(page);
});
