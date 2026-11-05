import { expect, test } from "@playwright/test";

// Real backend (playwright.gym.config.ts's webServer — a disposable uv-run uvicorn instance,
// throwaway secrets/DB, never the real .env/data/catch.db), real service worker, real
// IndexedDB. ?mock=1 never calls fetch at all, so it can't exercise any of offline-first
// logging, a dropped-connection retry, or the actual POST /api/gym/sessions/sync upsert —
// this suite is the substitute for session 14's "use it on my phone with airplane mode on"
// quality-bar item, which this environment has no real iPhone to do live (same gap session
// 10 documented and left as an explicit placeholder).
const TEST_PASSWORD = "correct-horse-battery-staple";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, { timeout: 15_000 });
  await page.locator("#password").fill(TEST_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Strain today")).toBeVisible({ timeout: 10_000 });
}

test("logging a full workout offline survives a reload and syncs once reconnected", async ({ page, context }) => {
  await login(page);

  // Visit /gym once online so the service worker's generic /api/* GET cache (vite.config.ts)
  // has something to serve offline — the exercise library, gyms, templates, muscle readiness.
  await page.goto("/gym");
  await expect(page.getByRole("button", { name: "Start blank workout" })).toBeVisible();
  await expect(page.getByText("Synced")).toBeVisible({ timeout: 10_000 }); // confirms the sync-status probe itself works online.

  await context.setOffline(true);

  await page.getByRole("button", { name: "Start blank workout" }).click();
  await page.getByRole("button", { name: "+ Add exercise" }).click();
  await page.getByPlaceholder("Search exercises…").fill("Barbell Squat");
  await page.getByText("Barbell Squat", { exact: true }).click();

  await expect(page.getByText("Barbell Squat")).toBeVisible();

  async function logOneSet(reps: number, loadKg: number) {
    await page.getByRole("spinbutton", { name: "Reps", exact: true }).fill(String(reps));
    await page.getByRole("spinbutton", { name: "Load kg", exact: true }).fill(String(loadKg));
    await page.getByRole("button", { name: "Log set" }).click();
  }

  await logOneSet(5, 60);
  await logOneSet(5, 70);
  await logOneSet(5, 80);

  // Three real sets, offline, no network path at all — the rest timer and the "N sets to
  // sync" badge are both driven off local IndexedDB state, never a server response.
  await expect(page.getByText("Set 1 · 5 reps")).toBeVisible();
  await expect(page.getByText("Set 3 · 5 reps")).toBeVisible();
  await expect(page.getByText("3 sets to sync")).toBeVisible();
  await expect(page.getByText("80kg")).toBeVisible(); // 60kg entered + 20kg default bar = 80kg effective (the first set is also a PR, shown alongside it).

  // "The connection drops or the app is closed" (task Part A.1) — a full reload while still
  // offline must not lose anything; the active session resumes straight from IndexedDB.
  await page.reload();
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, { timeout: 15_000 });
  await expect(page.getByText("Barbell Squat")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Set 3 · 5 reps")).toBeVisible();
  await expect(page.getByText("3 sets to sync")).toBeVisible();

  // Reconnect — the queue should flush on its own (useOnlineStatus going true), no user action.
  await context.setOffline(false);
  await expect(page.getByText("Synced")).toBeVisible({ timeout: 15_000 });

  // The real proof: ask the real backend directly, not just trust the UI's own optimistic state.
  const activities = await page.request.get("/api/activities?category=strength").then((r) => r.json());
  expect(activities.items.length).toBeGreaterThan(0);
  const strengthActivity = activities.items[0];
  expect(strengthActivity.muscular_load_au).toBeGreaterThan(0);

  const detail = await page.request.get(`/api/activities/${strengthActivity.id}`).then((r) => r.json());
  expect(detail.strength_sets).toHaveLength(3);
  expect(detail.strength_sets.map((s: { effective_load_kg: number }) => s.effective_load_kg).sort((a: number, b: number) => a - b)).toEqual([80, 90, 100]);
});
