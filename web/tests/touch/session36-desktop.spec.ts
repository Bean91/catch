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

test("week view: drag a planned session to another day with the mouse; a plain click still opens it", async ({ page }) => {
  await page.goto("/calendar?mock=1");
  const days = page.getByTestId("week-day");
  await expect(days).toHaveCount(7);
  const source = days.filter({ has: page.getByTestId("planned-drag") }).first();
  const fromDate = (await source.getAttribute("data-date"))!;
  const chip = source.getByTestId("planned-drag").first();
  const title = (await chip.locator("span.truncate.font-medium").textContent())!.trim();
  const dates = await days.evaluateAll((els) => els.map((e) => e.getAttribute("data-date")!));
  const toDate = dates.find((d) => d !== fromDate)!;
  const target = page.locator(`[data-testid="week-day"][data-date="${toDate}"]`);
  await chip.scrollIntoViewIfNeeded();
  const a = (await chip.boundingBox())!;
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await target.scrollIntoViewIfNeeded();
  const b = (await target.boundingBox())!;
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 });
  await expect(page.getByTestId("plan-drag-ghost")).toBeVisible();
  await expect(target).toHaveAttribute("data-drop-over", "true");
  await page.mouse.up();
  await expect(target.getByText(title, { exact: true })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0); // the drop didn't also open the sheet
  await target.getByTestId("planned-chip").filter({ hasText: title }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
});
