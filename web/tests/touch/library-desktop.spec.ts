import { expect, test, type Page } from "@playwright/test";

// The same screens at a 1280px desktop viewport with a mouse: the sidebar entries, two-column
// layouts, and sheets that open centred rather than from the bottom. ?mock=1 throughout.

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

async function noHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
}

test("the sidebar reaches the library and the feedback timeline", async ({ page }) => {
  await page.goto("/?mock=1");
  const side = page.locator("aside");
  await expect(side.getByRole("link", { name: "Feedback" })).toBeVisible();
  await side.getByRole("link", { name: "Library" }).click();
  await expect(page.getByRole("heading", { name: "Workout library" })).toBeVisible();
  await side.getByRole("link", { name: "Feedback" }).click();
  await expect(page.getByRole("heading", { name: "Coaching feedback" })).toBeVisible();
});

test("library lays templates out in two columns and schedules from a centred dialog", async ({ page }) => {
  await page.goto("/library?mock=1");
  const cards = page.getByTestId("template-card");
  await expect(cards).toHaveCount(3);
  const [a, b] = [await cards.nth(0).boundingBox(), await cards.nth(1).boundingBox()];
  expect(Math.abs((a?.y ?? 0) - (b?.y ?? 99))).toBeLessThan(4); // same row
  await noHorizontalOverflow(page);
  await cards.first().click();
  await page.getByTestId("add-to-calendar").click();
  const sheet = page.getByTestId("schedule-sheet");
  const box = await sheet.boundingBox();
  const vp = page.viewportSize()!;
  expect(box!.y).toBeGreaterThan(20);
  expect(box!.y + box!.height).toBeLessThan(vp.height - 20); // centred, not docked to the bottom
  await sheet.getByRole("button", { name: "Add to calendar" }).last().click();
  await expect(page.getByTestId("schedule-done")).toBeVisible();
});

test("the editor keeps its check panel beside the form, and Examples stay read-only", async ({ page }) => {
  await page.goto("/library/new?mock=1");
  await page.getByLabel("Template name").fill("Desktop one");
  const form = await page.getByRole("heading", { name: "Basics" }).boundingBox();
  const check = await page.getByTestId("editor-check").boundingBox();
  expect(check!.x).toBeGreaterThan(form!.x + form!.width - 1);
  await expect(page.getByTestId("save-template")).toBeEnabled();
  await noHorizontalOverflow(page);
  await page.goto("/library/20/edit?mock=1");
  await expect(page.getByText("Examples are read-only")).toBeVisible();
});

test("technique notes and feedback show privacy indicators and ownership on desktop too", async ({ page }) => {
  await page.goto("/workouts/6?mock=1");
  for (const n of await page.getByTestId("technique-note").all()) await expect(n.getByTestId("privacy-badge")).toHaveCount(1);
  await page.goto("/feedback?mock=1");
  const entries = page.getByTestId("feedback-entry");
  await expect(entries).toHaveCount(3);
  for (const e of await entries.all()) await expect(e.getByTestId("privacy-badge")).toHaveCount(1);
  await expect(entries.filter({ hasText: "Good rhythm" }).getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);
  await expect(entries.filter({ hasText: "sit taller" }).getByRole("button", { name: "Edit", exact: true })).toBeVisible();
  await noHorizontalOverflow(page);
});
