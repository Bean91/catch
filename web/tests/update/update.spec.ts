import type { Server } from "node:http";
import { expect, test } from "@playwright/test";
import { DIST_A, DIST_B } from "./globalSetup.mjs";
import { startServer } from "./server.mjs";

const PORT = 5192;
const BASE = `http://localhost:${PORT}`;

let server: Server;
let currentRoot = DIST_A;

test.beforeAll(async () => {
  server = await startServer(() => currentRoot, PORT);
});

test.afterAll(() => {
  server.close();
});

test.beforeEach(() => {
  currentRoot = DIST_A;
});

test("first-ever load of a build shows no update toast", async ({ page }) => {
  await page.goto(`${BASE}/settings?mock=1`);
  await expect(page.getByText(/Build build-a/)).toBeVisible();
  await page.waitForTimeout(1_500); // the version poll fires on mount; give it a moment either way
  await expect(page.getByText("New version — tap to reload")).toHaveCount(0);
});

test("detects a newly deployed build and reloads to pick it up", async ({ page }) => {
  await page.goto(`${BASE}/settings?mock=1`);
  await expect(page.getByText(/Build build-a/)).toBeVisible();

  currentRoot = DIST_B; // simulates ./deploy.sh shipping a new build under this open tab
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));

  const toast = page.getByText("New version — tap to reload");
  await expect(toast).toBeVisible({ timeout: 10_000 });

  // Tapping reload() just does window.location.reload() — a plain navigation, deliberately not
  // dependent on service-worker controllerchange timing (see useServiceWorkerUpdate.ts's
  // file-level comment on why the prior design was dropped).
  await toast.click();
  await expect(page.getByText(/Build build-b/)).toBeVisible({ timeout: 10_000 });

  await expect(async () => {
    const cacheNames = await page.evaluate(() => caches.keys());
    expect(cacheNames.some((n) => n.includes("build-b"))).toBe(true);
    expect(cacheNames.some((n) => n.includes("build-a"))).toBe(false);
  }).toPass({ timeout: 5_000 });
});

test("an offline mock scenario shows the banner with real data age, a healthy one does not", async ({ page }) => {
  await page.goto(`${BASE}/?mock=1`);
  await expect(page.getByText(/You're offline/)).toHaveCount(0);

  await page.goto(`${BASE}/?mock=offline`);
  await expect(page.getByText(/You're offline — showing data from/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/3h ago/)).toBeVisible();
});
