import { expect, test, type Page } from "@playwright/test";
import { newTouchSession, touchDrag, touchPinch } from "./cdpTouch";
import { noHorizontalOverflow, stubTiles } from "./mapStub";

// Session 20: the GPS route card on workout detail, against ?mock=1 fixtures, at the 390px iPhone
// profile (Chromium + WebKit). Mock on-water ids rotate through states (see lib/mockGps.ts):
// 1 = everything, 6 = partial weather, 11 = weather not fetched, 16 = no GPS recorded; 2 is an erg.

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

async function openWorkout(page: Page, id: number) {
  await page.goto(`/workouts/${id}?mock=1`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

test("the map chunk is not fetched until a GPS workout needs it, and then renders a route", async ({ page }) => {
  const tiles = await stubTiles(page);
  const chunks: string[] = [];
  page.on("request", (r) => {
    if (/RouteMap|leaflet/i.test(r.url())) chunks.push(r.url());
  });
  await page.goto("/?mock=1");
  await expect(page.locator("main, #root").first()).toBeVisible();
  await page.waitForTimeout(500);
  expect(chunks, "Today must not pull in the map chunk").toEqual([]);

  await openWorkout(page, 1);
  // The placeholder sits below the fold; the real map (and its chunk) loads as it nears the viewport.
  await page.getByTestId("lazy-route-map").scrollIntoViewIfNeeded();
  const map = page.getByTestId("route-map");
  await expect(map).toBeVisible({ timeout: 10_000 });
  await expect(map.locator(".leaflet-overlay-pane path").first()).toBeAttached();
  expect(await map.locator(".leaflet-overlay-pane path").count()).toBeGreaterThan(3); // speed-ramp runs + markers
  await expect.poll(tiles.count).toBeGreaterThan(0);
  await expect(page.locator(".leaflet-control-attribution")).toContainText("OpenStreetMap");
  expect(chunks.length).toBeGreaterThan(0);
});

test("no horizontal scrolling on the workout, routes and route-detail pages", async ({ page }) => {
  await stubTiles(page);
  for (const path of ["/workouts/1?mock=1", "/workouts/6?mock=1", "/workouts?mock=1", "/routes?mock=1", "/routes/1?mock=1"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForTimeout(300);
    expect(await noHorizontalOverflow(page), path).toBeLessThanOrEqual(0);
  }
});

test("GPS figures say where they came from, and Garmin's own numbers sit apart", async ({ page }) => {
  await stubTiles(page);
  await openWorkout(page, 1);
  await expect(page.getByRole("heading", { name: "GPS metrics" })).toBeVisible();
  expect(await page.locator('[data-source="gps_derived"]').count()).toBeGreaterThan(4);
  const provider = page.getByTestId("provider-figures");
  await expect(provider).toContainText("What Garmin reported");
  await expect(provider.locator('[data-source="provider"]').first()).toBeVisible();
  await expect(provider).toContainText("neither replaces the other");
  await expect(page.getByTestId("environment-note")).toContainText("not corrected for wind, current or water conditions");
  await page.getByText("How the GPS track was filtered").click();
  await expect(page.getByTestId("filter-report")).toContainText("implausible jumps dropped");
  await expect(page.getByTestId("filter-report")).toContainText("doesn't report GPS accuracy");
});

test("splits follow the chosen distance", async ({ page }) => {
  await stubTiles(page);
  await openWorkout(page, 1);
  const rows = page.getByTestId("splits-table").locator("tbody tr");
  await expect(rows).toHaveCount(16); // 7700 m / 500 m = 15.4 -> 15 full + 1 partial
  await page.getByRole("tab", { name: "1 km" }).click();
  await expect(rows).toHaveCount(8);
  await expect(rows.last()).toContainText("partial 700 m");
  await page.getByRole("tab", { name: "250 m" }).click();
  await expect(rows).toHaveCount(31);
});

test("weather states are shown as they are: ok, partial, not fetched", async ({ page }) => {
  await stubTiles(page);
  await openWorkout(page, 1);
  await expect(page.getByTestId("weather-status")).toHaveAttribute("data-status", "ok");
  await expect(page.getByTestId("weather-chips")).toContainText("wind 18 km/h from WNW");
  await expect(page.getByRole("link", { name: /Open-Meteo/ })).toHaveAttribute("href", "https://open-meteo.com/");
  await expect(page.getByText("never as a performance correction")).toBeVisible();

  await openWorkout(page, 6);
  await expect(page.getByTestId("weather-status")).toHaveAttribute("data-status", "partial");
  await expect(page.getByText("not available").first()).toBeVisible(); // temperature missing stays visibly missing
  await expect(page.getByText("the gaps are not filled in")).toBeVisible();

  await openWorkout(page, 11);
  await expect(page.getByTestId("weather-status")).toHaveAttribute("data-status", "not_fetched");
  await expect(page.getByRole("button", { name: "Look up" })).toBeVisible();
  await expect(page.getByTestId("weather-chips")).toHaveCount(0);
});

test("an on-water row with no GPS says so, and an erg shows no GPS card at all", async ({ page }) => {
  await stubTiles(page);
  await openWorkout(page, 16);
  await expect(page.getByTestId("no-gps")).toContainText("No GPS data has been read");
  await expect(page.getByTestId("route-map")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "GPS metrics" })).toHaveCount(0);

  await openWorkout(page, 2); // an erg row
  await expect(page.getByRole("heading", { name: "Route & GPS" })).toHaveCount(0);
  await expect(page.getByTestId("no-gps")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Pieces" })).toBeVisible(); // the rest of the page is untouched
});

test("a one-finger swipe over the map scrolls the page; two fingers zoom the map", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "multi-touch/move gestures need CDP (Chromium only)");
  await stubTiles(page);
  await openWorkout(page, 1);
  await page.getByTestId("lazy-route-map").scrollIntoViewIfNeeded();
  const map = page.getByTestId("route-map");
  await expect(map).toBeVisible({ timeout: 10_000 });
  await map.scrollIntoViewIfNeeded();
  const box = (await map.boundingBox())!;
  const cdp = await newTouchSession(page);
  const center = { x: box.x + box.width / 2, y: Math.min(box.y + box.height / 2, 400) };

  const y0 = await page.evaluate(() => window.scrollY);
  await touchDrag(cdp, { x: center.x, y: center.y + 120 }, { x: center.x, y: center.y - 120 }, { steps: 12 });
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(y0 + 40); // the page moved: the map did not trap the swipe
  await expect(page.getByTestId("map-hint")).toContainText("two fingers");

  await map.scrollIntoViewIfNeeded();
  const b2 = (await map.boundingBox())!;
  const c2 = { x: b2.x + b2.width / 2, y: Math.min(b2.y + b2.height / 2, 400) };
  const z0 = Number(await map.getAttribute("data-zoom"));
  await touchPinch(cdp, c2, 30, 110, 14);
  await expect.poll(async () => Number(await map.getAttribute("data-zoom"))).toBeGreaterThan(z0);
});

test("the speed/pace chart shows a readout on touch without taking over scrolling", async ({ page }) => {
  await stubTiles(page);
  await openWorkout(page, 1);
  const surface = page.getByTestId("track-chart-surface");
  await surface.scrollIntoViewIfNeeded();
  expect(await surface.evaluate((el) => getComputedStyle(el).touchAction)).toBe("pan-y");
  await page.getByRole("tab", { name: "Speed" }).click();
  await expect(page.getByRole("tab", { name: "Speed" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: "Elevation" })).toHaveCount(0); // this device recorded none
});

test("routes: list, history with caveats, rename and tag", async ({ page }) => {
  await stubTiles(page);
  await page.goto("/routes?mock=1");
  await expect(page.getByRole("link", { name: /Westport · 7.7 km/ })).toBeVisible();
  await page.getByRole("link", { name: /Westport · 7.7 km/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Westport");

  await expect(page.getByTestId("history-caveats")).toContainText("not wind-, current- or water-corrected");
  await expect(page.getByTestId("speed-histogram")).toBeVisible();
  await expect(page.getByTestId("route-sessions").locator("tbody tr")).toHaveCount(4);
  await expect(page.getByTestId("weather-differences")).toContainText("wind speed");
  await expect(page.getByText("Observed provider data, not a correction.")).toBeVisible();

  await page.getByRole("heading", { level: 1 }).click();
  await page.getByLabel("Route name").fill("Home course");
  await page.getByLabel("Route name").press("Enter");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Home course");
  await page.getByLabel("Route tags").fill("steady, lake");
  await page.getByLabel("Route tags").blur();
  await expect(page.getByLabel("Route tags")).toHaveValue("steady, lake");
});

test("a workout on a route links to it, and a session can be taken off it", async ({ page }) => {
  await stubTiles(page);
  await openWorkout(page, 1);
  const chip = page.getByTestId("route-chip");
  await expect(chip.getByRole("link")).toBeVisible();
  await chip.getByRole("button", { name: "Not this route" }).click();
  await expect(chip).toContainText("Not part of a repeated route yet");
  await expect(chip.getByRole("button", { name: "Save this course as a route" })).toBeVisible();
});
