import { expect, test, type Route } from "@playwright/test";
import { mockSettings, mockZonesView } from "../../src/lib/mock";

// Session 33: Settings cards load on their own. Production measured every Settings request at 150–350 ms alone and ~30 s together
// (a pool deadlock, fixed server-side); this guards the page side: one failing endpoint and one slow one must not hold up the
// rest, a failure shows a Retry instead of "Loading…" forever, and opening Settings never asks for a provider's model list.

const GOTRUE = "http://supabase.test/auth/v1";
const json = (route: Route, status: number, body: unknown) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

function session() {
  return {
    access_token: "token-a",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: "refresh-a",
    user: { id: "user-a", aud: "authenticated", role: "authenticated", email: "a@example.com", app_metadata: {}, user_metadata: {}, created_at: "2026-11-01T00:00:00Z" },
  };
}

test("a failing card shows Retry, a slow card doesn't block the others, and no model list is fetched", async ({ page }) => {
  let illnessFails = true;
  const requested: string[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    requested.push(path);
    if (path === "/api/settings") return json(route, 200, mockSettings());
    if (path === "/api/zones") return json(route, 200, mockZonesView());
    if (path === "/api/illness/backtest") return illnessFails ? json(route, 500, { detail: "boom" }) : json(route, 200, { flagged: [], marked_count: 0, precision: null });
    if (path === "/api/coach/settings") {
      await new Promise((r) => setTimeout(r, 4000));
      return json(route, 503, { detail: "slow" });
    }
    if (path === "/api/me") return json(route, 200, { id: "user-a", email: "a@example.com", deployment: "public", timezone: "UTC", follow_device_zone: false, current_zone: "UTC", today: "2026-11-21", onboarding: { state: "completed", show: false } });
    return json(route, 503, { detail: "mock" });
  });
  await page.route(`${GOTRUE}/token?grant_type=password`, (route) => json(route, 200, session()));
  await page.goto("/");
  await page.getByLabel("Email").fill("a@example.com");
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByLabel("Email")).toBeHidden(); // signed in (the session is stored) before navigating
  await page.goto("/settings");

  // Settings-backed cards render while the coach settings request is still hanging.
  const started = Date.now();
  await expect(page.getByTestId("hr-zones-card")).toBeVisible({ timeout: 3000 });
  await expect(page.getByRole("heading", { name: "Appearance" })).toBeVisible();
  expect(Date.now() - started).toBeLessThan(3000);
  await expect(page.getByRole("heading", { name: "AI coach" })).toBeVisible();

  // The failed card says so and recovers on Retry.
  const failed = page.getByText("Couldn't load the flagged nights.");
  await expect(failed).toBeVisible();
  illnessFails = false;
  await failed.locator("xpath=..").getByRole("button", { name: "Retry" }).click();
  await expect(page.getByText("No flagged nights yet.")).toBeVisible();

  await expect(page.getByText("Couldn't load the AI coach settings.")).toBeVisible({ timeout: 10_000 });
  expect(requested.some((p) => /\/api\/ai\/providers\/[^/]+\/models/.test(p))).toBe(false);
});

// A page that throws must not take the app with it. On a native build, a stale cached settings shape made Settings throw, and with no
// error boundary React unmounted everything: a black screen with no navigation. Here the server's settings lack the zone tables.
test("a page that crashes shows an error in place and keeps the navigation", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/settings") return json(route, 200, { ...mockSettings(), zones: {} });
    if (path === "/api/zones") return json(route, 200, mockZonesView());
    if (path === "/api/me") return json(route, 200, { id: "user-a", email: "a@example.com", deployment: "public", timezone: "UTC", follow_device_zone: false, current_zone: "UTC", today: "2026-11-21", onboarding: { state: "completed", show: false } });
    return json(route, 503, { detail: "mock" });
  });
  await page.route(`${GOTRUE}/token?grant_type=password`, (route) => json(route, 200, session()));
  await page.goto("/");
  await page.getByLabel("Email").fill("a@example.com");
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByLabel("Email")).toBeHidden();
  await page.goto("/settings");

  await expect(page.getByTestId("page-error")).toBeVisible();
  const today = page.getByRole("link", { name: "Today", exact: true }).filter({ visible: true }).first(); // bottom nav or sidebar
  await expect(today).toBeVisible();
  await today.click(); // leaving the broken page clears the error
  await expect(page.getByTestId("page-error")).toHaveCount(0);
});
