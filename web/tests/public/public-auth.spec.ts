import { expect, test, type Page, type Route } from "@playwright/test";
import { mockSettings } from "../../src/lib/mock";

const GOTRUE = "http://supabase.test/auth/v1";

function session(userId: string, token: string, refresh = `refresh-${token}`) {
  return {
    access_token: token,
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: refresh,
    user: { id: userId, aud: "authenticated", role: "authenticated", email: `${userId}@example.com`, app_metadata: {}, user_metadata: {}, created_at: "2026-11-01T00:00:00Z" },
  };
}

const json = (route: Route, status: number, body: unknown) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

interface Calls {
  api: { url: string; auth: string | undefined; method: string }[];
}

async function mockBackend(page: Page, opts: { apiStatus?: (call: number, auth: string | undefined) => number } = {}): Promise<Calls> {
  const calls: Calls = { api: [] };
  await page.route("**/api/**", (route) => {
    const req = route.request();
    const auth = req.headers()["authorization"];
    calls.api.push({ url: new URL(req.url()).pathname, auth, method: req.method() });
    const path = new URL(req.url()).pathname;
    // Only what the flows need; everything else is a clean 503 so cards show their error state instead of crashing.
    const known = path === "/api/sync/status" || path === "/api/health" || path === "/api/settings";
    const status = opts.apiStatus ? opts.apiStatus(calls.api.length, auth) : known ? 200 : 503;
    if (status !== 200) return json(route, status, { detail: status === 401 ? "Not authenticated" : "mock" });
    return json(route, 200, path === "/api/settings" ? mockSettings() : path === "/api/sync/status" ? [] : {});
  });
  return calls;
}

async function signIn(page: Page, userId = "user-a", token = "token-a") {
  await page.route(`${GOTRUE}/token?grant_type=password`, (route) => json(route, 200, session(userId, token)));
  await page.goto("/");
  await page.getByLabel("Email").fill("a@example.com");
  await page.getByLabel("Password").fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("the public build asks for an email and a password, and says so plainly when sign-up needs confirming", async ({ page }) => {
  await mockBackend(page);
  await page.route(`${GOTRUE}/signup**`, (route) => json(route, 200, { id: "new", aud: "authenticated", email: "n@example.com" })); // a user, no session
  await page.goto("/");
  await expect(page.getByLabel("Email")).toBeVisible();
  await page.getByRole("button", { name: "New here? Create an account" }).click();
  await page.getByLabel("Email").fill("n@example.com");
  await page.getByLabel("Password").fill("short");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("alert")).toContainText("at least 8 characters");
  await page.getByLabel("Password").fill("long-enough-password");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("status")).toContainText("Check your email");
});

test("password reset answers the same way for any address", async ({ page }) => {
  await mockBackend(page);
  let asked = 0;
  await page.route(`${GOTRUE}/recover**`, (route) => {
    asked += 1;
    return json(route, 200, {});
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Forgot your password?" }).click();
  await page.getByLabel("Email").fill("anyone@example.com");
  await page.getByRole("button", { name: "Reset password" }).click();
  await expect(page.getByRole("status")).toContainText("If that address has an account");
  expect(asked).toBe(1);
});

test("a wrong password shows one generic message", async ({ page }) => {
  await mockBackend(page);
  await page.route(`${GOTRUE}/token?grant_type=password`, (route) => json(route, 400, { code: "invalid_credentials", message: "Invalid login credentials" }));
  await page.goto("/");
  await page.getByLabel("Email").fill("a@example.com");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Incorrect email or password.");
});

test("once signed in, every API call carries the access token and no cookie is relied on", async ({ page }) => {
  const calls = await mockBackend(page);
  await signIn(page);
  await expect.poll(() => calls.api.length).toBeGreaterThan(0);
  const authed = calls.api.filter((c) => c.url !== "/api/health"); // the online probe is deliberately unauthenticated
  expect(authed.length).toBeGreaterThan(0);
  expect(authed.every((c) => c.auth === "Bearer token-a")).toBe(true);
});

test("a 401 refreshes the token once and retries; the person never sees a sign-in screen", async ({ page }) => {
  const calls = await mockBackend(page, { apiStatus: (_n, auth) => (auth === "Bearer token-a" ? 401 : 200) });
  let refreshes = 0;
  await page.route(`${GOTRUE}/token?grant_type=refresh_token`, (route) => {
    refreshes += 1;
    return json(route, 200, session("user-a", "token-b"));
  });
  await signIn(page);
  await expect.poll(() => calls.api.some((c) => c.auth === "Bearer token-b")).toBe(true);
  expect(refreshes).toBeGreaterThanOrEqual(1);
  await expect(page.getByLabel("Email")).toHaveCount(0);
});

test("when the session was revoked, the refresh fails and the person is signed out with their local data cleared", async ({ page }) => {
  await mockBackend(page, { apiStatus: () => 401 });
  await page.route(`${GOTRUE}/token?grant_type=refresh_token`, (route) => json(route, 400, { code: "refresh_token_not_found", message: "Invalid Refresh Token" }));
  await page.route(`${GOTRUE}/logout**`, (route) => json(route, 204, {}));
  await page.goto("/");
  await page.evaluate(async () => {
    localStorage.setItem("catch:lastAuthed", "1");
    localStorage.setItem("catch:something", "private");
    await new Promise<void>((resolve) => {
      const open = indexedDB.open("catch-gym", 1);
      open.onupgradeneeded = () => open.result.createObjectStore("sets");
      open.onsuccess = () => {
        open.result.close();
        resolve();
      };
    });
  });
  await signIn(page);
  await expect(page.getByLabel("Email")).toBeVisible({ timeout: 10_000 });
  expect(await page.evaluate(() => localStorage.getItem("catch:something"))).toBeNull();
  const dbs = await page.evaluate(async () => (await indexedDB.databases()).map((d) => d.name));
  expect(dbs).not.toContain("catch-gym");
});

test("signing in as a different person on the same browser wipes the previous person's local data first", async ({ page }) => {
  await mockBackend(page);
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.setItem("catch:uid", "user-a");
    localStorage.setItem("catch:something", "a's private data");
  });
  await signIn(page, "user-b", "token-b");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("catch:uid"))).toBe("user-b");
  expect(await page.evaluate(() => localStorage.getItem("catch:something"))).toBeNull();
});

test("deleting the account needs the typed confirmation, calls the API once, and signs out", async ({ page }) => {
  await mockBackend(page);
  let deleted = 0;
  await page.route(`${GOTRUE}/logout**`, (route) => json(route, 204, {}));
  await page.route("**/api/account", (route) => {
    if (route.request().method() === "DELETE") deleted += 1;
    return json(route, 200, { deleted: true, files_removed: 0 });
  });
  await page.route("**/api/settings", (route) => json(route, 200, mockSettings()));
  await signIn(page);
  await expect(page.getByLabel("Email")).toHaveCount(0); // signed in (and the session saved) before navigating away
  await page.goto("/settings");
  await page.getByRole("button", { name: "Delete account…" }).click();
  const confirmButton = page.getByRole("button", { name: "Delete everything" });
  await expect(confirmButton).toBeDisabled();
  await page.getByLabel("Type DELETE to confirm").fill("DELETE");
  await confirmButton.click();
  await expect(page.getByLabel("Email")).toBeVisible({ timeout: 10_000 });
  expect(deleted).toBe(1);
});
