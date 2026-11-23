import { expect, test } from "@playwright/test";

// Session 36, desktop mouse: pointing at one chart shows the same moment on the other (the PM5's strokes and the heart-rate chart
// are the same recording in this mock workout), and the Performance Lab lays out in two columns without overflow.

test("pointing at the erg chart moves the heart-rate chart's cursor too, and back", async ({ page }) => {
  await page.goto("/workouts/3?mock=1");
  await expect(page.getByTestId("chart-sync-note")).toContainText("Linked to the heart-rate chart");
  const surfaces = page.locator('[data-chart-surface="true"]');
  const erg = page.getByRole("img", { name: /over distance/ });
  await erg.scrollIntoViewIfNeeded();
  const box = (await erg.boundingBox())!;
  // The chart engine shows a mouse's crosshair while the button is down (a press inspects; see useChartInteraction).
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.3);
  await page.mouse.down();
  await expect(page.getByTestId("erg-tooltip")).toBeVisible();
  await expect(page.getByTestId("hr-chart-tooltip")).toBeVisible();
  await page.mouse.up();
  await page.mouse.move(0, 0);

  const hr = page.getByRole("img", { name: /Heart rate over elapsed time/ });
  await hr.scrollIntoViewIfNeeded();
  const hbox = (await hr.boundingBox())!;
  await page.mouse.move(hbox.x + hbox.width * 0.4, hbox.y + hbox.height * 0.4);
  await page.mouse.down();
  await expect(page.getByTestId("erg-tooltip")).toBeVisible();
  await page.mouse.up();
  expect(await surfaces.count()).toBeGreaterThan(1);
});

test("performance lab at desktop width", async ({ page }) => {
  await page.goto("/lab?mock=1");
  await expect(page.getByTestId("records-card")).toBeVisible();
  await expect(page.getByTestId("progression-card")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
