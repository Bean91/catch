import { expect, test, type Page } from "@playwright/test";
import { addDays, todayISO, weekStart } from "../../src/lib/dates";

// Calendar interaction at the iPhone 13 profile (390px wide), driven with real touch taps. Runs
// under both mobile projects, real WebKit included. Everything runs against ?mock=1, whose
// fixtures are built relative to the browser's local "today" (src/lib/mockCalendar.ts), so the
// dates below are derived the same way rather than hard-coded.

const T = todayISO();
const MON = weekStart(T);
const W3 = addDays(MON, 21);

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("bottom nav still fits eight labels at 390px, with the calendar tab", async ({ page }) => {
  await page.goto("/?mock=1");
  const nav = page.getByRole("navigation", { name: "Primary" });
  await expect(nav.getByRole("link")).toHaveCount(8);
  const clipped = await nav.locator("a span").evaluateAll((els) => els.filter((el) => el.scrollWidth > el.clientWidth).map((el) => el.textContent));
  expect(clipped, `nav labels truncated at 390px: ${clipped.join(", ")}`).toEqual([]);
  const navOverflow = await nav.evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(navOverflow).toBeLessThanOrEqual(0);
  await nav.getByRole("link", { name: "Plan" }).tap();
  await expect(page).toHaveURL(/\/calendar/);
  await expect(page.getByRole("heading", { name: "Calendar" })).toBeVisible();
});

test("week view lists seven days with no sideways scroll", async ({ page }) => {
  await page.goto("/calendar?mock=1&view=week");
  await expect(page.getByTestId("week-day")).toHaveCount(7);
  await noHorizontalOverflow(page);
  await expect(page.getByTestId("week-summary")).toBeVisible();
  await expect(page.getByTestId("phase-banner")).toContainText("Coach-approved");
});

test("planned, completed, skipped and not-logged sessions are visually and textually distinct, with no shaming words", async ({ page }) => {
  await page.goto(`/calendar?mock=1&view=day&date=${addDays(T, -3)}`);
  const notLogged = page.locator('[data-status="not_logged"]');
  await expect(notLogged).toContainText("Not logged");
  await page.goto(`/calendar?mock=1&view=day&date=${addDays(T, -1)}`);
  await expect(page.locator('[data-status="skipped"]')).toContainText("Skipped");
  await page.goto(`/calendar?mock=1&view=day&date=${T}`);
  const planned = page.locator('[data-status="planned"]');
  await expect(planned).toContainText("Planned");

  const styles = await page.evaluate(() => getComputedStyle(document.querySelector('[data-status="planned"]')!).borderTopStyle);
  expect(styles).toBe("solid");
  await page.goto(`/calendar?mock=1&view=day&date=${addDays(T, -3)}`);
  const dashed = await page.locator('[data-status="not_logged"]').evaluate((el) => getComputedStyle(el).borderTopStyle);
  expect(dashed).toBe("dashed");

  // A linked/completed day reads "Done"/"Completed" — a different label again.
  await page.goto(`/calendar?mock=1&view=day&date=${addDays(T, -9)}`);
  await expect(page.locator('[data-status="linked"]')).toContainText("Done");
  await expect(page.getByTestId("completed-chip")).toContainText("Completed");

  for (const offset of [-3, -2, -1, 0]) {
    await page.goto(`/calendar?mock=1&view=day&date=${addDays(T, offset)}`);
    await expect(page.getByTestId("day-view")).toBeVisible();
    const text = (await page.locator("main, body").first().innerText()).toLowerCase();
    for (const word of ["missed", "behind", "overdue", "failed", "lazy"]) expect(text).not.toContain(word);
  }
});

test("a matching workout is suggested, never linked automatically; accepting or declining works", async ({ page }) => {
  await page.goto(`/calendar?mock=1&view=day&date=${addDays(T, -2)}`);
  const suggestion = page.getByTestId("link-suggestion");
  await expect(suggestion).toContainText("Link them?");
  await expect(page.locator('[data-status="not_logged"]')).toBeVisible(); // still unlinked until the athlete says so
  await expect(suggestion).toContainText("Both records stay as they are");

  await suggestion.getByRole("button", { name: "Not this one" }).tap();
  await expect(page.getByTestId("link-suggestion")).toHaveCount(0);
  await expect(page.locator('[data-status="not_logged"]')).toBeVisible();
});

test("accepting a suggestion links the plan to the workout", async ({ page }) => {
  await page.goto(`/calendar?mock=1&view=day&date=${addDays(T, -2)}`);
  await page.getByTestId("link-suggestion").getByRole("button", { name: "Link them" }).tap();
  await expect(page.locator('[data-status="linked"]')).toContainText("Done");
  await expect(page.getByTestId("link-suggestion")).toHaveCount(0);
  await page.getByRole("button", { name: "Unlink workout" }).tap();
  await expect(page.locator('[data-status="not_logged"]')).toBeVisible();
});

test("adding a planned session: the sheet's save button is reachable above the bottom nav", async ({ page }) => {
  await page.goto("/calendar?mock=1&view=week");
  await expect(page.getByTestId("week-day")).toHaveCount(7);
  const before = await page.getByTestId("planned-chip").count();
  await page.getByRole("button", { name: /^Plan a session on/ }).first().tap();
  const sheet = page.getByTestId("planned-sheet");
  await expect(sheet).toBeVisible();

  // The z-30 rule (DESIGN.md): the Add button must be what a tap at its centre actually hits,
  // not the z-20 bottom nav painted over it.
  const button = sheet.getByRole("button", { name: "Add to plan" });
  await button.scrollIntoViewIfNeeded();
  const hit = await button.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return top === el || el.contains(top);
  });
  expect(hit).toBe(true);

  await sheet.getByLabel("Title (optional)").fill("Evening spin");
  await sheet.getByLabel("Type").selectOption("bike");
  await sheet.getByLabel("Duration (min)").fill("45");
  await button.tap();
  await expect(sheet).toHaveCount(0);
  await expect(page.getByTestId("planned-chip")).toHaveCount(before + 1);
  await expect(page.getByText("Evening spin")).toBeVisible();
  await noHorizontalOverflow(page);
});

test("a planned session can be moved a day with the Later button", async ({ page }) => {
  const pyramidDay = addDays(T, 2);
  await page.goto(`/calendar?mock=1&view=day&date=${pyramidDay}`);
  await page.getByRole("button", { name: /Pyramid/ }).tap();
  const sheet = page.getByTestId("planned-sheet");
  await sheet.getByRole("button", { name: "Later →" }).tap();
  await expect(sheet).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Pyramid/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Next" }).tap();
  await expect(page.getByRole("button", { name: /Pyramid/ })).toBeVisible();
});

test("a repeating plan creates a series and can be removed from a point on", async ({ page }) => {
  await page.goto(`/calendar?mock=1&view=month&date=${W3}`);
  await page.getByRole("button", { name: "+ Plan", exact: true }).tap();
  const sheet = page.getByTestId("planned-sheet");
  await sheet.getByLabel("Title (optional)").fill("Series row");
  await sheet.getByLabel("Duration (min)").fill("30");
  await sheet.getByLabel("Repeat weekly").check();
  await sheet.getByRole("button", { name: "Add to plan" }).tap();
  await expect(sheet).toHaveCount(0);
  await page.getByRole("tab", { name: "Week" }).tap();
  await expect(page.getByText("Series row")).toHaveCount(1);
  await page.getByRole("button", { name: "Next" }).tap();
  await expect(page.getByText("Series row")).toHaveCount(1); // one per week, four weeks by default
});

test("month view: dot grid with labels; tapping a day opens it", async ({ page }) => {
  await page.goto("/calendar?mock=1&view=month");
  await expect(page.getByTestId("month-view")).toBeVisible();
  await noHorizontalOverflow(page);
  const cell = page.locator(`[data-testid="month-cell"][data-date="${T}"]`);
  await expect(cell).toHaveAttribute("aria-label", /planned/);
  await cell.tap();
  await expect(page.getByRole("tab", { name: "Day" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("day-view")).toBeVisible();
});

test("a large planned jump shows a calm review note that defers to the coach on an approved phase", async ({ page }) => {
  await page.goto(`/calendar?mock=1&view=week&date=${W3}`);
  const flags = page.getByTestId("review-flags");
  await expect(flags).toContainText("Worth a look");
  await expect(flags).toContainText("coach-approved");
  await expect(flags).toContainText("nothing has been changed");
  const text = (await flags.innerText()).toLowerCase();
  for (const word of ["missed", "behind", "failed", "must", "should"]) expect(text).not.toContain(word);
});

test("race detail: countdown, goals, projection with data, assumptions and uncertainty", async ({ page }) => {
  await page.goto("/calendar/events/2?mock=1");
  await expect(page.getByRole("heading", { name: "Club 2k test" })).toBeVisible();
  await expect(page.getByTestId("countdown")).toContainText("12");
  const projection = page.getByTestId("projection");
  await expect(projection).toContainText("likely range");
  await expect(projection).toContainText("Assumptions");
  await expect(projection).toContainText("Uncertainty");
  await expect(page.getByText("Test history")).toBeVisible();
  await noHorizontalOverflow(page);
});

test("a race with no standard distance says why it has no projection instead of guessing", async ({ page }) => {
  await page.goto("/calendar/events/1?mock=1");
  await expect(page.getByTestId("projection-unavailable")).toContainText("No projection yet");
  await expect(page.getByText("Top 10")).toBeVisible();
});

test("the notification deep link route renders for an event", async ({ page }) => {
  // check_test_reminder links to /calendar/events/{id}; the service worker postMessages that path
  // and App.tsx navigates — here the destination itself must render from a cold load.
  await page.goto("/calendar/events/2?mock=1");
  await expect(page.getByTestId("countdown")).toBeVisible();
  await page.goto("/calendar/events/999?mock=1");
  await expect(page.getByText("Couldn't find that event.")).toBeVisible();
});

test("Today shows upcoming events and links to the event page", async ({ page }) => {
  await page.goto("/?mock=1");
  const card = page.getByTestId("upcoming-events");
  await expect(card).toContainText("Club 2k test");
  await card.getByRole("link", { name: /Club 2k test/ }).tap();
  await expect(page).toHaveURL(/\/calendar\/events\/2/);
});

test("training plan page: phases with approval state, weekly bars, no sideways scroll", async ({ page }) => {
  await page.goto("/calendar/plan?mock=1");
  await expect(page.getByTestId("phase-list")).toContainText("Coach-approved");
  await expect(page.getByTestId("plan-weeks").getByRole("listitem")).toHaveCount(7);
  await noHorizontalOverflow(page);
  await page.getByTestId("phase-list").getByRole("button").first().tap();
  const sheet = page.getByTestId("phase-sheet");
  await expect(sheet).toContainText("Coach approval");
  await expect(sheet).toContainText("Approved by Coach Sam");
});

test("changing a coach-approved phase's plan shows 'edited since approval'", async ({ page }) => {
  await page.goto("/calendar/plan?mock=1");
  await page.getByTestId("phase-list").getByRole("button").first().tap();
  const sheet = page.getByTestId("phase-sheet");
  await sheet.getByLabel("Minutes / week").fill("480");
  await sheet.getByRole("button", { name: "Save changes" }).tap();
  await expect(sheet).toHaveCount(0);
  await expect(page.getByTestId("phase-list")).toContainText("edited since");
});

test("the event editor creates an event that then shows on Today's list", async ({ page }) => {
  await page.goto("/calendar?mock=1&view=week");
  await page.getByRole("button", { name: "+ Event" }).tap();
  const sheet = page.getByTestId("event-sheet");
  await sheet.getByLabel("Name").fill("Spring regatta");
  await sheet.getByLabel("Date").fill(addDays(T, 5));
  await sheet.getByLabel("Importance").selectOption("B");
  await sheet.getByRole("button", { name: "Add event" }).tap();
  await expect(sheet).toHaveCount(0);
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Today" }).tap();
  await expect(page.getByTestId("upcoming-events")).toContainText("Spring regatta");
});
