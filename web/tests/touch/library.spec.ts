import { expect, test, type Locator, type Page } from "@playwright/test";
import { todayISO } from "../../src/lib/dates";

// Workout library, technique notes and coach feedback at the iPhone 13 profile (390px), driven with
// real touch taps. Runs under both mobile projects, real WebKit included. Everything is ?mock=1; the
// mock state lives in memory per page load, so flows stay inside the SPA (clicking links, never
// page.goto between steps) and every test starts from the same fixtures.

const BANNED = /\b(missed|behind|overdue|failed|failure|lazy|poor technique|bad technique|technique score|technique rating)\b/i;

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

async function aboveNav(page: Page, target: Locator) {
  // The sheet's primary button must be what a finger would hit, not the bottom nav behind it.
  // Re-scrolled on every poll: a web font that finishes loading after the sheet opens re-wraps
  // its text and grows the sheet, which strands a scroll position computed a moment earlier.
  await expect
    .poll(async () => {
      await target.scrollIntoViewIfNeeded();
      return target.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return !!top && (el === top || el.contains(top));
      });
    })
    .toBe(true);
}

test("library lists my templates, tabs to examples with a clear not-prescribed label, no sideways scroll", async ({ page }) => {
  await page.goto("/library?mock=1");
  await expect(page.getByRole("heading", { name: "Workout library" })).toBeVisible();
  await expect(page.getByTestId("template-card")).toHaveCount(3);
  await expect(page.getByTestId("example-badge")).toHaveCount(0);
  await noHorizontalOverflow(page);
  await page.getByRole("tab", { name: "Examples" }).tap();
  await expect(page.getByTestId("example-notice")).toContainText("not training advice");
  const cards = page.getByTestId("template-card");
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThanOrEqual(5);
  await expect(page.getByTestId("example-badge")).toHaveCount(await cards.count());
  await expect(page.getByTestId("example-badge").first()).toContainText("Example — not prescribed training");
  await noHorizontalOverflow(page);
  await page.getByRole("tab", { name: "Archived" }).tap();
  await expect(page.getByTestId("template-card")).toHaveCount(1);
  expect(await page.locator("body").innerText()).not.toMatch(BANNED);
});

test("search and type filter narrow the list", async ({ page }) => {
  await page.goto("/library?mock=1");
  await page.getByLabel("Search templates").fill("steady");
  await expect(page.getByTestId("template-card")).toHaveCount(1);
  await page.getByLabel("Search templates").fill("");
  await page.getByRole("tab", { name: "Erg intervals" }).tap();
  await expect(page.getByTestId("template-card")).toHaveCount(2);
});

test("template detail shows structure and honest totals, then schedules onto the calendar", async ({ page }) => {
  await page.goto("/library?mock=1");
  await page.getByTestId("template-card").filter({ hasText: "Threshold 4 x 5 min" }).tap();
  await expect(page.getByTestId("template-title")).toHaveText("Threshold 4 x 5 min");
  await expect(page.getByTestId("structure-block")).toHaveCount(1);
  await expect(page.getByTestId("summary-total")).toContainText("min");
  await noHorizontalOverflow(page);

  await page.getByTestId("add-to-calendar").tap();
  const sheet = page.getByTestId("schedule-sheet");
  await expect(sheet).toBeVisible();
  await expect(sheet).toContainText("an intention, not a workout");
  await aboveNav(page, sheet.getByRole("button", { name: "Add to calendar" }).last());
  await sheet.getByRole("button", { name: "Add to calendar" }).last().tap();
  await expect(page.getByTestId("schedule-done")).toContainText("Planned 1 session");
  await page.getByRole("link", { name: "View in calendar" }).tap();
  await expect(page).toHaveURL(/\/calendar/);
  await expect(page.getByTestId("planned-chip").filter({ hasText: "Threshold 4 x 5 min" })).toBeVisible();
});

test("a distance-only template says its duration is unknown instead of showing zero", async ({ page }) => {
  await page.goto("/library?mock=1");
  await page.getByTestId("template-card").filter({ hasText: "6 x 500m (no split set)" }).tap();
  await expect(page.getByTestId("summary-total")).toHaveText("Not set");
  await expect(page.getByTestId("template-summary")).toContainText("until you set a split or watts target");
});

test("create, duplicate, archive: the whole library lifecycle", async ({ page }) => {
  await page.goto("/library?mock=1");
  await page.getByTestId("new-template").tap();
  await page.getByLabel("Template name").fill("My 4 x 500");
  await expect(page.getByTestId("editor-check")).toContainText("Not set");
  await page.getByLabel("Block 1 split").fill("1:50");
  await expect(page.getByTestId("editor-check").getByTestId("summary-total")).toContainText("min");
  await expect(page.getByTestId("editor-check")).toContainText("Estimated");
  await noHorizontalOverflow(page);
  await page.getByTestId("save-template").tap();
  await expect(page.getByTestId("template-title")).toHaveText("My 4 x 500");

  await page.getByTestId("duplicate").tap();
  await expect(page.getByTestId("template-title")).toHaveText("My 4 x 500 (copy)");
  await page.getByTestId("archive").tap();
  await expect(page.getByTestId("archive")).toHaveText("Unarchive");
  await page.getByRole("link", { name: "← Library" }).tap();
  await expect(page.getByTestId("template-card").filter({ hasText: "(copy)" })).toHaveCount(0);
  await page.getByRole("tab", { name: "Archived" }).tap();
  await expect(page.getByTestId("template-card").filter({ hasText: "(copy)" })).toHaveCount(1);
});

test("editing validates through the server and blocks saving a bad template", async ({ page }) => {
  await page.goto("/library/new?mock=1");
  await page.getByLabel("Template name").fill("Ladder");
  await page.getByLabel("Workout type").selectOption("rate_ladder");
  await expect(page.getByTestId("block-row")).toHaveCount(3);
  await page.getByLabel("Remove block 3").tap();
  await page.getByLabel("Remove block 2").tap();
  await expect(page.getByTestId("issue")).toContainText("at least two steps");
  await expect(page.getByTestId("save-template")).toBeDisabled();
  await page.getByTestId("add-block").tap();
  await expect(page.getByTestId("save-template")).toBeEnabled();
  await page.getByLabel("Block 1 work", { exact: true }).fill("abc");
  await expect(page.getByTestId("editor-check")).toContainText("enter the time like 4:00");
  await expect(page.getByTestId("save-template")).toBeDisabled();
});

test("examples can't be edited, only duplicated", async ({ page }) => {
  await page.goto("/library?mock=1");
  await page.getByRole("tab", { name: "Examples" }).tap();
  await page.getByTestId("template-card").first().tap();
  await expect(page.getByText("Example — not prescribed training").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Edit" })).toHaveCount(0);
  await page.getByTestId("duplicate").tap();
  await expect(page.getByRole("link", { name: "Edit" })).toBeVisible();
});

test("technique notes on a workout carry a privacy badge each, default private, and never a score", async ({ page }) => {
  await page.goto("/workouts/6?mock=1");
  const card = page.getByTestId("technique-notes");
  await expect(card).toContainText("Catch can't see technique in this data");
  const notes = card.getByTestId("technique-note");
  await expect(notes).toHaveCount(2);
  for (const n of await notes.all()) await expect(n.getByTestId("privacy-badge")).toHaveCount(1);
  await expect(notes.filter({ hasText: "Reaching with the arms" }).getByTestId("privacy-badge")).toContainText("Private — only you");
  await expect(notes.filter({ hasText: "Legs-body-arms" }).getByTestId("privacy-badge")).toContainText("Shared with coach");

  await page.getByTestId("add-note").tap();
  const sheet = page.getByTestId("note-sheet");
  await expect(sheet.getByRole("radio", { name: /Private — only you/ })).toHaveAttribute("aria-checked", "true");
  await aboveNav(page, sheet.getByRole("button", { name: "Save note" }));
  await sheet.getByLabel("Your note").fill("Sat taller through the drive");
  await sheet.getByRole("radio", { name: /Share with my coach/ }).tap();
  await sheet.getByRole("button", { name: "Save note" }).tap();
  const added = page.getByTestId("technique-note").filter({ hasText: "Sat taller" });
  await expect(added.getByTestId("privacy-badge")).toContainText("Shared with coach");
  expect(await page.getByTestId("technique-notes").innerText()).not.toMatch(BANNED);
  await noHorizontalOverflow(page);
});

test("feedback timeline: a coach's entry is read-only, the athlete can respond, edits keep history", async ({ page }) => {
  await page.goto("/feedback?mock=1");
  await expect(page.getByRole("heading", { name: "Coaching feedback" })).toBeVisible();
  const entries = page.getByTestId("feedback-entry");
  await expect(entries).toHaveCount(3);
  for (const e of await entries.all()) await expect(e.getByTestId("privacy-badge")).toHaveCount(1);

  const coachEntry = entries.filter({ hasText: "Good rhythm" });
  await expect(coachEntry).toContainText("Coach Sam");
  await expect(coachEntry.getByTestId("read-only-note")).toContainText("only they can edit it");
  await expect(coachEntry.getByRole("button", { name: "Edit", exact: true })).toHaveCount(0);
  await expect(coachEntry.getByTestId("athlete-response")).toContainText("hands-away cue");
  await expect(coachEntry.getByTestId("privacy-badge")).toContainText("Shared with you");

  await coachEntry.getByRole("button", { name: /Edited · history/ }).tap();
  await expect(coachEntry.getByTestId("feedback-history")).toContainText("Good rhythm in the last three pieces.");

  const mine = entries.filter({ hasText: "sit taller" });
  await expect(mine.getByTestId("privacy-badge")).toContainText("Private — only you");
  await expect(mine.getByRole("button", { name: "Edit", exact: true })).toBeVisible();

  const other = entries.filter({ hasText: "Race plan" });
  await other.getByTestId("respond").tap();
  await other.getByLabel("Your response").fill("Got it");
  await other.getByRole("button", { name: "Save response" }).tap();
  await expect(other.getByTestId("athlete-response")).toContainText("Got it");
  await noHorizontalOverflow(page);
  expect(await page.locator("body").innerText()).not.toMatch(BANNED);
});

test("feedback filters by coach, focus area and date", async ({ page }) => {
  await page.goto("/feedback?mock=1");
  const filters = page.getByTestId("feedback-filters");
  await filters.getByLabel("Coach").selectOption("Coach Lee");
  await expect(page.getByTestId("feedback-entry")).toHaveCount(1);
  await expect(page.getByTestId("feedback-entry")).toContainText("Race plan");
  await filters.getByLabel("Coach").selectOption("");
  await filters.getByLabel("Focus").selectOption("posture");
  await expect(page.getByTestId("feedback-entry")).toHaveCount(1);
  await filters.getByLabel("Focus").selectOption("");
  await filters.getByLabel("From").fill(todayISO());
  await expect(page.getByText("No feedback matches those filters.")).toBeVisible();
});

test("logging feedback: private/shared choice is explicit and the sheet is tappable above the nav", async ({ page }) => {
  await page.goto("/feedback?mock=1");
  await page.getByTestId("log-feedback").tap();
  const sheet = page.getByTestId("feedback-sheet");
  await aboveNav(page, sheet.getByRole("button", { name: "Save entry" }));
  await sheet.getByLabel("Feedback", { exact: true }).fill("Keep the hands moving first");
  await sheet.getByLabel("From which coach? (optional)").fill("Coach Kim");
  await sheet.getByRole("radio", { name: /Private — only you/ }).tap();
  await sheet.getByRole("button", { name: "Save entry" }).tap();
  const added = page.getByTestId("feedback-entry").filter({ hasText: "Keep the hands moving first" });
  await expect(added).toHaveAttribute("data-visibility", "private");
  await expect(added.getByTestId("privacy-badge")).toContainText("Private — only you");
  await expect(added).toContainText("Coach Kim · logged by you");
});

test("technique notes section on the feedback page filters by category and shows privacy on each note", async ({ page }) => {
  await page.goto("/feedback?mock=1");
  const notes = page.getByTestId("technique-note");
  await expect(notes).toHaveCount(4);
  for (const n of await notes.all()) await expect(n.getByTestId("privacy-badge")).toHaveCount(1);
  await page.getByRole("tab", { name: "Posture" }).tap();
  await expect(notes).toHaveCount(1);
  await page.getByRole("tab", { name: "Rate control" }).tap();
  await expect(notes.first().getByRole("link", { name: "Rate drill video" })).toHaveAttribute("rel", "noopener noreferrer");
});

test("a planned session scheduled from a template links back to it", async ({ page }) => {
  await page.goto("/library?mock=1");
  await page.getByTestId("template-card").filter({ hasText: "Sunday long steady" }).tap();
  await page.getByTestId("add-to-calendar").tap();
  await page.getByTestId("schedule-sheet").getByRole("button", { name: "Add to calendar" }).last().tap();
  await page.getByRole("link", { name: "View in calendar" }).tap();
  await page.getByTestId("planned-chip").filter({ hasText: "Sunday long steady" }).first().tap();
  await expect(page.getByTestId("from-template")).toContainText("From a library template");
});
