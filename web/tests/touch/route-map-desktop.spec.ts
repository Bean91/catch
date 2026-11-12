import { expect, test } from "@playwright/test";
import { stubTiles } from "./mapStub";

// The built app registers a service worker whose fetches bypass page.route in WebKit, which let real
// OpenStreetMap tiles through the stub. Blocking it keeps these specs off the network.
test.use({ serviceWorkers: "block" });

// Session 20, desktop mouse: the map must not hijack page scroll (wheel zooms only with
// ctrl/cmd), drag pans, and the speed/pace chart's crosshair drives a marker on the map.

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await stubTiles(page);
  await page.goto("/workouts/1?mock=1");
  await page.getByTestId("lazy-route-map").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("route-map")).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("route-map").scrollIntoViewIfNeeded();
});

test("a plain wheel over the map scrolls the page and leaves the zoom alone", async ({ page }) => {
  const map = page.getByTestId("route-map");
  const z0 = await map.getAttribute("data-zoom");
  const box = (await map.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const y0 = await page.evaluate(() => window.scrollY);
  await page.mouse.wheel(0, 300);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(y0);
  expect(await map.getAttribute("data-zoom")).toBe(z0);
});

test("ctrl+wheel zooms the map", async ({ page }) => {
  const map = page.getByTestId("route-map");
  const z0 = Number(await map.getAttribute("data-zoom"));
  const box = (await map.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.keyboard.down("Control");
  for (let i = 0; i < 4; i++) await page.mouse.wheel(0, -120);
  await page.keyboard.up("Control");
  await expect.poll(async () => Number(await map.getAttribute("data-zoom"))).toBeGreaterThan(z0);
});

test("dragging pans the map", async ({ page }) => {
  const map = page.getByTestId("route-map");
  const c0 = await map.getAttribute("data-center");
  const box = (await map.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.4, { steps: 8 });
  await page.mouse.up();
  await expect.poll(async () => map.getAttribute("data-center")).not.toBe(c0);
});

test("hovering the speed chart moves a marker on the map", async ({ page }) => {
  const paths = page.getByTestId("route-map").locator(".leaflet-overlay-pane path");
  const before = await paths.count();
  const surface = page.getByTestId("track-chart-surface");
  await surface.scrollIntoViewIfNeeded();
  const box = (await surface.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await expect(page.getByTestId("track-chart-tooltip")).toBeVisible();
  await expect.poll(() => paths.count()).toBe(before + 1);
  await page.mouse.move(box.x + box.width * 0.5, box.y - 80);
  await expect.poll(() => paths.count()).toBe(before);
});

test("the desktop sidebar links to Routes", async ({ page }) => {
  await page.getByRole("link", { name: "Routes", exact: true }).first().click();
  await expect(page).toHaveURL(/\/routes/);
  await expect(page.getByRole("heading", { level: 1, name: "Routes" })).toBeVisible();
});
