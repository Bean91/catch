import { expect, test } from "@playwright/test";
import { newTouchSession, touchDrag, touchHold, touchPinch, touchTap } from "./cdpTouch";

// Regression coverage for the real-iPhone touch bug: session 8's own testing only used
// Chromium's CDP touch emulation, which didn't reproduce it. These tests run under the
// `mobile-gestures` project (Chromium + an iPhone device profile, driven via CDP multi-touch —
// see cdpTouch.ts/playwright.config.ts) and are skipped elsewhere, since Playwright's WebKit
// bindings can't synthesize touch move or multi-touch at all.

test.beforeEach(async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "multi-touch/move gestures need CDP (Chromium only)");
  await page.emulateMedia({ reducedMotion: "reduce" }); // deterministic: skips the one-time draw-in animation
  await page.goto("/trends?mock=1&range=12w");
  await expect(page.getByRole("img", { name: /Trend over time/ })).toBeVisible();
  // The 12-week preset's *view* window never depends on the metric's full-history query, but
  // `fullDomain` (what pan/zoom can reach) does — it briefly falls back to "now - 84d" until
  // that query resolves (see Trends.tsx's `earliestMs`/PLAN.md's session 8 bug log). Wait for
  // the navigator's real floor before testing pan, or a drag toward older history would be
  // clamped right back to the still-narrow fallback and look like a dead gesture.
  await expect
    .poll(async () => Number(await page.locator('[role="slider"]').getAttribute("aria-valuemin")), { timeout: 3000 })
    .toBeLessThan(Date.now() - 100 * 86_400_000);
});

async function chartBox(page: import("@playwright/test").Page) {
  const box = await page.locator('[data-chart-surface="true"]').first().boundingBox();
  if (!box) throw new Error("chart surface has no bounding box");
  return box;
}

// The chart's data points are dense enough (12 weeks padded to ~20 weeks, in a ~300px-wide
// plot) that any x inside the plot area lands within TAP_PROXIMITY_PX of *some* point — so
// this doesn't need to hit an exact rendered vertex, just the horizontal center of the chart.
// What it does need to get right is y: at this viewport height the chart card's own bottom
// edge sits *under* the fixed BottomNav (confirmed empirically: innerHeight 664 vs. the chart
// surface's own rect.bottom of 698), so a geometrically-reasonable y can still be genuinely
// un-tappable. Scanning a few fractions and checking elementFromPoint asks the browser
// directly, rather than keep guessing at layout.
async function onScreenChartPoint(page: import("@playwright/test").Page) {
  const target = await page.evaluate(() => {
    const surface = document.querySelector('[data-chart-surface="true"]') as HTMLElement;
    const rect = surface.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    for (const frac of [0.5, 0.35, 0.65, 0.2, 0.8]) {
      const y = rect.top + rect.height * frac;
      const el = document.elementFromPoint(x, y);
      if (el && surface.contains(el)) return { x, y };
    }
    return null;
  });
  if (!target) throw new Error("no on-screen, actually-tappable chart point found");
  return target;
}

test("chart surfaces compute touch-action: none", async ({ page }) => {
  const actions = await page.locator('[data-chart-surface="true"]').evaluateAll((els) => els.map((el) => getComputedStyle(el).touchAction));
  expect(actions.length).toBeGreaterThan(0);
  for (const a of actions) expect(a).toBe("none");
});

test("horizontal drag pans the chart and does not scroll the page", async ({ page }) => {
  const box = await chartBox(page);
  const before = await page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label");
  const scrollBefore = await page.evaluate(() => window.scrollY);

  const cdp = await newTouchSession(page);
  const midY = box.y + box.height / 2;
  // Left-to-right: the 12-week preset's window already ends at "now" (the live edge), so a
  // right-to-left drag — standard "swipe to reveal more recent/future content" — has nowhere
  // to go and would look like a dead gesture for the wrong reason. Dragging the other way
  // reveals older history, where fullDomain actually has room (see beforeEach's wait above).
  await touchDrag(cdp, { x: box.x + box.width * 0.25, y: midY }, { x: box.x + box.width * 0.75, y: midY });

  await expect
    .poll(async () => page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label"), { timeout: 2000 })
    .not.toBe(before);
  expect(await page.evaluate(() => window.scrollY)).toBe(scrollBefore);
});

test("vertical drag scrolls the page and does not pan the chart", async ({ page }) => {
  // The page needs room to scroll — Trends has several cards below the fold at this viewport.
  const box = await chartBox(page);
  const before = await page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label");
  const scrollBefore = await page.evaluate(() => window.scrollY);

  const cdp = await newTouchSession(page);
  const midX = box.x + box.width / 2;
  await touchDrag(cdp, { x: midX, y: box.y + box.height * 0.8 }, { x: midX, y: box.y + box.height * 0.2 });

  await expect.poll(async () => page.evaluate(() => window.scrollY), { timeout: 2000 }).toBeGreaterThan(scrollBefore);
  expect(await page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label")).toBe(before);
});

test("pinch zooms the chart in (narrower visible range)", async ({ page }) => {
  const box = await chartBox(page);
  const center = { x: box.x + box.width / 2, y: box.y + box.height / 2 };

  const cdp = await newTouchSession(page);
  await touchPinch(cdp, center, 20, 140); // fingers moving apart = zoom in

  await expect
    .poll(
      async () => {
        const label = await page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label");
        const match = label?.match(/Showing (.+) to (.+)$/);
        if (!match) return null;
        return (new Date(match[2]).getTime() - new Date(match[1]).getTime()) / 86_400_000;
      },
      { timeout: 2000 },
    )
    .toBeLessThan(84); // started at the 12-week (84-day) preset
});

test("press-and-hold shows the crosshair tooltip without panning or navigating", async ({ page }) => {
  const box = await chartBox(page);
  const before = await page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label");
  const urlBefore = page.url();

  const cdp = await newTouchSession(page);
  const holdDone = touchHold(cdp, { x: box.x + box.width / 2, y: box.y + box.height / 2 }, 600);

  // The tooltip must appear *during* the hold (after the ~300ms threshold, before release) —
  // this is what makes it a press-and-hold inspect rather than nothing happening until a tap.
  await expect(page.getByTestId("chart-tooltip")).toBeVisible({ timeout: 1000 });
  await holdDone;

  expect(await page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label")).toBe(before);
  expect(page.url()).toBe(urlBefore);
});

// Switching metric starts a brand-new full-history query for that metric, which briefly
// re-triggers the same "fullDomain floor still at the 84-day fallback" state the top-level
// beforeEach already waits out for the default metric (see its comment).
async function selectMetricAndWaitForStableChart(page: import("@playwright/test").Page, label: string) {
  await page.getByRole("tab", { name: label }).click();
  await expect(page.locator('[data-testid="chart-line"]')).toBeVisible();
  await page.waitForTimeout(800);
}

// Retries kept as cheap insurance (Playwright's own per-test retry, not a custom loop): an
// earlier version of `selectMetricAndWaitForStableChart` used `expect.poll` here too, which
// reproduced a real, repeatable failure — the chart tapped at the right coordinates but never
// navigated. Confirmed by hand (fixed-delay scripts, no `expect.poll`, run 15+ times back to
// back) that the tap mechanism itself (pointerdown -> delayed onTap -> navigate) is correct;
// swapping the poll for a fixed wait here made the flakiness disappear across repeated full
// runs. The exact mechanism by which repeated `getAttribute` polling perturbed timing enough to
// matter was not fully root-caused — logged here rather than silently trusting a config change
// that merely stopped reproducing it.
test.describe(() => {
  test.describe.configure({ retries: 2 });

  test("a quick tap on a tappable (W/kg) point navigates to that workout", async ({ page }) => {
    await selectMetricAndWaitForStableChart(page, "W/kg");

    const target = await onScreenChartPoint(page);
    const cdp = await newTouchSession(page);
    await touchTap(cdp, target);

    await expect(page).toHaveURL(/\/workouts\/\d+/, { timeout: 2000 });
  });

  test("a cancelled tap (touchcancel) never navigates", async ({ page }) => {
    await selectMetricAndWaitForStableChart(page, "W/kg");

    const target = await onScreenChartPoint(page);
    const urlBefore = page.url();
    const cdp = await newTouchSession(page);
    await touchDrag(cdp, target, target, { cancel: true });

    await page.waitForTimeout(500); // longer than the 350ms double-tap delay, to prove it never fires
    expect(page.url()).toBe(urlBefore);
  });
});
