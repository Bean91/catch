import { expect, test } from "@playwright/test";

// The "mouse" half of the task's "mouse and iPhone touch profiles" CI requirement — runs only
// under the `desktop-mouse` project (see playwright.config.ts's per-project testMatch/
// testIgnore), a real mouse/trackpad/keyboard input path through `useChartInteraction.ts`
// rather than touch emulation. Covers the two interactions DESIGN.md documents as mouse-only
// (ctrl/cmd+wheel zoom, drag-to-pan) which the CDP-touch suite in charts.spec.ts can't exercise.

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/trends?mock=1&range=12w");
  await expect(page.getByRole("img", { name: /Trend over time/ })).toBeVisible();
  await expect
    .poll(async () => Number(await page.locator('[role="slider"]').getAttribute("aria-valuemin")), { timeout: 3000 })
    .toBeLessThan(Date.now() - 100 * 86_400_000);
});

async function chartBox(page: import("@playwright/test").Page) {
  const box = await page.locator('[data-chart-surface="true"]').first().boundingBox();
  if (!box) throw new Error("chart surface has no bounding box");
  return box;
}

function rangeDays(label: string | null): number | null {
  const match = label?.match(/Showing (.+) to (.+)$/);
  if (!match) return null;
  return (new Date(match[2]).getTime() - new Date(match[1]).getTime()) / 86_400_000;
}

test("ctrl+wheel zooms the chart in (narrower visible range)", async ({ page }) => {
  const box = await chartBox(page);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);

  await page.keyboard.down("Control");
  // Several small wheel ticks rather than one big one — matches a real trackpad pinch/wheel
  // stream closer than a single large delta would.
  for (let i = 0; i < 6; i++) await page.mouse.wheel(0, -120);
  await page.keyboard.up("Control");

  await expect
    .poll(async () => rangeDays(await page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label")), {
      timeout: 2000,
    })
    .toBeLessThan(84); // started at the 12-week (84-day) preset
});

test("mouse drag pans the chart (left-to-right reveals older history)", async ({ page }) => {
  const box = await chartBox(page);
  const before = await page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label");
  const midY = box.y + box.height / 2;

  await page.mouse.move(box.x + box.width * 0.25, midY);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.75, midY, { steps: 10 });
  await page.mouse.up();

  await expect
    .poll(async () => page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label"), { timeout: 2000 })
    .not.toBe(before);
});

test("double-click resets zoom/pan back to the preset range", async ({ page }) => {
  const box = await chartBox(page);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -400);
  await page.keyboard.up("Control");
  await expect
    .poll(async () => rangeDays(await page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label")), {
      timeout: 2000,
    })
    .toBeLessThan(84);

  await page.mouse.dblclick(box.x + box.width / 2, box.y + box.height / 2);

  await expect
    .poll(async () => rangeDays(await page.getByRole("img", { name: /Trend over time/ }).getAttribute("aria-label")), {
      timeout: 2000,
    })
    .toBeCloseTo(84, 0);
});
