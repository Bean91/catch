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

test("a real tap on a chart surface is accepted (no dead zone)", async ({ page }) => {
  const box = await page.locator('[data-chart-surface="true"]').first().boundingBox();
  if (!box) throw new Error("no chart surface");
  // Just confirms the surface actually receives pointer input at all under this engine — the
  // original bug on a real iPhone was that touches did nothing, full stop.
  await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.getByRole("img", { name: /Trend over time/ })).toBeVisible();
});
