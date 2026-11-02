import { expect, test } from "@playwright/test";

// Runs under both projects, including real WebKit (see playwright.config.ts) — these don't
// need touch move or multi-touch, so Playwright's own `page.touchscreen` is enough, and real
// WebKit is worth running separately: it's the one engine that actually reproduced the
// original bug, so a computed-style check here is a closer approximation to a real iPhone
// than Chromium's equivalent.

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/trends?mock=1&range=12w");
  await expect(page.getByRole("img", { name: /Trend over time/ })).toBeVisible();
});

test("every chart surface is touch-action: none", async ({ page }) => {
  // Not asserting -webkit-touch-callout here: neither Chromium nor Playwright's bundled WebKit
  // exposes it through getComputedStyle (it's an iOS-Safari-specific UIKit behavior, not a
  // generically-implemented CSS property), so there's nothing for either engine to report back
  // — the rule in index.css is still correct and worth keeping, just not verifiable this way.
  const actions = await page.locator('[data-chart-surface="true"]').evaluateAll((els) => els.map((el) => getComputedStyle(el).touchAction));
  expect(actions.length).toBeGreaterThan(0);
  for (const a of actions) expect(a).toBe("none");
});

test("the page body still allows native scrolling (pan-x pan-y)", async ({ page }) => {
  const bodyTouchAction = await page.evaluate(() => getComputedStyle(document.body).touchAction);
  expect(bodyTouchAction).toBe("pan-x pan-y");
});

test("a real touchscreen tap on a tappable point navigates (not just 'still visible')", async ({ page }) => {
  // Deliberately NOT just "the chart is still there after tapping" — that would pass even if
  // touches were silently swallowed, which is exactly the original bug. Asserting navigation
  // forces the tap to have gone through the real engine's touch -> pointer event pipeline,
  // the shared gesture hook, and React Router's navigate() end to end.
  await page.getByRole("tab", { name: "W/kg" }).click();
  await expect(page.locator('[data-testid="chart-line"]')).toBeVisible();
  await page.waitForTimeout(800); // see charts.spec.ts's selectMetricAndWaitForStableChart

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

  await page.touchscreen.tap(target.x, target.y);
  await expect(page).toHaveURL(/\/workouts\/\d+/, { timeout: 2000 });
});

test("no on-chart zoom buttons — they covered data at 390px (see DESIGN.md)", async ({ page }) => {
  await expect(page.getByRole("button", { name: "Zoom in" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Zoom out" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reset zoom" })).toHaveCount(0);
});

test("keyboard +/- zooms a focused chart and Escape resets it", async ({ page }) => {
  // Regression test for a real bug this session: a ref-mirror line in useChartInteraction.ts
  // was stomping the rAF-deferred live-domain flush before it fired, so every settled: true
  // commit (every keyboard action, since those never go through a drag) silently updated the
  // URL/query but never the visible chart or its aria-label.
  const chart = page.locator('[data-chart-surface="true"]').first();
  await chart.focus();
  const before = await page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label");

  await chart.press("=");
  await expect
    .poll(async () => page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label"), { timeout: 2000 })
    .not.toBe(before);

  await page.keyboard.press("Escape");
  await expect
    .poll(async () => page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label"), { timeout: 2000 })
    .toBe(before);
});
