import { expect, test, type Page } from "@playwright/test";
import { newTouchSession, touchDrag } from "./cdpTouch";

// Session 36 follow-up, both mobile projects at 390px against ?mock=1: press-and-hold drag to reschedule, the cross-device erg/HR
// alignment (proposed, then confirmed), the best-power curve, template folders and the calendar download.

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

async function center(page: Page, selector: ReturnType<Page["locator"]>) {
  await selector.scrollIntoViewIfNeeded();
  const box = (await selector.boundingBox())!;
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

test("week view: hold a planned session and drag it to another day; a quick swipe moves nothing; undo puts it back", async ({ page, browserName }) => {
  test.skip(browserName === "webkit", "CDP touch synthesis is Chromium-only (see cdpTouch.ts)");
  await page.goto("/calendar?mock=1");
  const days = page.getByTestId("week-day");
  await expect(days).toHaveCount(7);
  const source = days.filter({ has: page.getByTestId("planned-drag") }).first();
  const fromDate = await source.getAttribute("data-date");
  const chip = source.getByTestId("planned-drag").first();
  const title = (await chip.locator("span.truncate.font-medium").textContent())!.trim();
  const all = await days.evaluateAll((els) => els.map((e) => e.getAttribute("data-date")));
  const toDate = all[(all.indexOf(fromDate) + 1) % 7] === fromDate ? all[0] : all[(all.indexOf(fromDate) + 1) % 7];
  const target = page.locator(`[data-testid="week-day"][data-date="${toDate}"]`);
  const cdp = await newTouchSession(page);

  // A swipe that never held still is a scroll: nothing moves.
  const from = await center(page, chip);
  const to = await center(page, target);
  await touchDrag(cdp, from, to, { holdMs: 0, steps: 8 });
  await expect(source.getByText(title, { exact: true })).toBeVisible();

  // Press and hold, then drag onto the next day.
  const from2 = await center(page, chip);
  const to2 = await center(page, target);
  await touchDrag(cdp, from2, to2, { holdMs: 500, steps: 12 });
  await expect(target.getByText(title, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Undo" })).toBeVisible();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.locator(`[data-testid="week-day"][data-date="${fromDate}"]`).getByText(title, { exact: true })).toBeVisible();
  await noSidewaysScroll(page);
});

test("a tap on a planned session still opens it", async ({ page }) => {
  await page.goto("/calendar?mock=1");
  await page.getByTestId("planned-chip").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
});

test("two devices: nothing links until an offset is confirmed; a proposed offset can be used, then unlinked", async ({ page }) => {
  await page.goto("/workouts/13?mock=1");
  const note = page.getByTestId("erg-alignment");
  await note.scrollIntoViewIfNeeded();
  await expect(note).toContainText("Not linked to the heart-rate chart");
  await note.getByRole("button", { name: "Find the offset" }).click();
  const proposal = page.getByTestId("erg-alignment-suggestion");
  await expect(proposal).toContainText("0:42 into the heart-rate recording");
  await expect(proposal).toContainText("A proposal, not a measurement");
  await proposal.getByRole("button", { name: "Use this offset" }).click();
  await expect(note).toContainText("Linked to the heart-rate chart at the offset you set");
  await note.getByRole("button", { name: "Change offset" }).click();
  const editor = page.getByTestId("erg-alignment-editor");
  await editor.getByRole("button", { name: "+5 s" }).click();
  await expect(page.getByTestId("erg-offset-input")).toHaveValue("47");
  await editor.getByRole("button", { name: "Save offset" }).click();
  await expect(note).toContainText("0:47 into");
  await note.getByRole("button", { name: "Unlink" }).click();
  await expect(note).toContainText("Not linked");
  await noSidewaysScroll(page);
});

test("performance lab: best power for each duration, labelled as derived", async ({ page }) => {
  await page.goto("/lab?mock=1");
  const card = page.getByTestId("power-curve-card");
  await card.scrollIntoViewIfNeeded();
  await expect(card).toContainText("612 W");
  await expect(card).toContainText("Derived, not measured");
  await expect(card.getByRole("link", { name: "455 W" }).first()).toHaveAttribute("href", "/workouts/1");
  await expect(card).not.toContainText("1 h");  // no recording covers an hour: the row isn't shown
  await noSidewaysScroll(page);
});

test("library: filter by folder; examples have none; the editor sets one", async ({ page }) => {
  await page.goto("/library?mock=1");
  await page.getByTestId("folder-filter").selectOption("Winter base");
  await expect(page.getByTestId("template-folder-label")).toHaveCount(2);
  await page.getByRole("tab", { name: "Examples" }).click();
  await expect(page.getByTestId("folder-filter")).toHaveCount(0);
  await expect(page.getByTestId("template-folder-label")).toHaveCount(0);
  await page.goto("/library/new?mock=1");
  await expect(page.getByTestId("template-folder")).toBeVisible();
  await noSidewaysScroll(page);
});

test("calendar: download the plan as an .ics file", async ({ page }) => {
  await page.goto("/calendar?mock=1");
  const box = page.getByTestId("calendar-download");
  await box.scrollIntoViewIfNeeded();
  const download = page.waitForEvent("download");
  await box.getByRole("button", { name: "Download .ics" }).click();
  expect((await download).suggestedFilename()).toMatch(/^catch-calendar-\d{8}\.ics$/);
  await noSidewaysScroll(page);
});
