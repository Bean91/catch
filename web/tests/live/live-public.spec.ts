import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const MAILPIT = process.env.CATCH_TEST_MAILPIT_URL ?? "http://127.0.0.1:54324";
test.use({ viewport: { width: 1280, height: 1100 } }); // the sidebar's Log out sits below the fold of a 720 px window
test.skip(!process.env.CATCH_TEST_SUPABASE_URL, "needs a local Supabase stack (see playwright.live.config.ts)");

const PASSWORD = "correct-horse-battery-staple";
const NEW_PASSWORD = "an-entirely-new-passphrase";

async function mailLink(request: APIRequestContext, email: string, contains: RegExp): Promise<string> {
  for (let i = 0; i < 40; i++) {
    const list = await (await request.get(`${MAILPIT}/api/v1/search`, { params: { query: `to:${email}` } })).json();
    for (const m of list.messages ?? []) {
      const full = await (await request.get(`${MAILPIT}/api/v1/message/${m.ID}`)).json();
      const body: string = `${full.HTML ?? ""} ${full.Text ?? ""}`;
      if (!contains.test(body) && !contains.test(full.Subject ?? "")) continue;
      const link = body.match(/https?:\/\/[^\s"'<>]*\/auth\/v1\/verify[^\s"'<>]*/);
      if (link) return link[0].replace(/&amp;/g, "&");
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`no mail for ${email}`);
}


// The visible "Log out" (header icon on small screens, sidebar on large): clicking through the DOM sidesteps Playwright's
// actionability wait, which stalls on the sidebar when its bottom sits below the fold.
async function logOut(page: Page) {
  const clicked = await page.evaluate(() => {
    const buttons = [...document.querySelectorAll("button")].filter((b) => /log out/i.test(`${b.textContent} ${b.getAttribute("aria-label") ?? ""}`));
    const target = buttons.find((b) => (b as HTMLElement).offsetParent !== null) ?? buttons[buttons.length - 1];
    target?.click();
    return Boolean(target);
  });
  expect(clicked).toBe(true);
}

function watch(page: Page) {
  const seen = { violations: [] as string[], consoleCsp: [] as string[], api: [] as { url: string; auth?: string; status?: number }[], pageErrors: [] as string[] };
  page.on("console", (m) => {
    if (/content security policy/i.test(m.text())) seen.consoleCsp.push(m.text());
  });
  page.on("response", (r) => { if (r.url().includes("/auth/v1/")) console.log("AUTH", r.status(), new URL(r.url()).pathname); });
  page.on("pageerror", (e) => seen.pageErrors.push(e.message));
  const byRequest = new Map<unknown, { url: string; auth?: string; status?: number }>();
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (!u.pathname.startsWith("/api/") || u.pathname === "/api/health") return;
    const entry = { url: u.pathname, auth: r.headers()["authorization"] };
    byRequest.set(r, entry);
    seen.api.push(entry);
  });
  page.on("response", (r) => {
    const entry = byRequest.get(r.request());
    if (entry) entry.status = r.status();
  });
  return seen;
}

test("sign up → confirm by email → the app renders under the real CSP → reset the password → sign in again", async ({ page, request, context }) => {
  await context.addInitScript(() => {
    (window as unknown as { __csp: string[] }).__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => (window as unknown as { __csp: string[] }).__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  const seen = watch(page);
  const email = `live-${Date.now()}@example.com`;

  console.log("step 1");
  // 1. the document is served with the strict policy
  const doc = await page.goto("/");
  const csp = doc!.headers()["content-security-policy"];
  expect(csp).toContain("default-src 'self'");
  expect(csp).toMatch(/script-src 'self' 'wasm-unsafe-eval' 'sha256-/);
  expect(csp).toContain("connect-src 'self' http://127.0.0.1:54321");
  expect(doc!.headers()["x-frame-options"]).toBe("DENY");

  console.log("step 2");
  // 2. sign up: with confirmation required, the app says "check your email"
  await page.getByRole("button", { name: "New here? Create an account" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("status")).toContainText("Check your email");

  console.log("step 3");
  // 3. the confirmation link, opened in the SAME browser context (the PKCE verifier lives there), signs the person in
  await page.goto(await mailLink(request, email, /confirm/i));
  await expect(page.getByLabel("Email")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.locator("main, nav").first()).toBeVisible();

  console.log("step 4");
  // 4. real API calls carry the token, succeed, and the account card knows who is signed in
  await page.goto("/settings");
  await expect(page.getByTestId("account-card")).toContainText(email, { timeout: 15_000 });
  expect(seen.api.length).toBeGreaterThan(0);
  expect(seen.api.every((a) => a.auth?.startsWith("Bearer "))).toBe(true);
  expect(seen.api.some((a) => a.url === "/api/sync/status" && a.status === 200)).toBe(true);

  console.log("step 5");
  // 5. nothing the policy forbids was attempted
  expect(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).toEqual([]);
  expect(seen.consoleCsp).toEqual([]);
  expect(seen.pageErrors).toEqual([]);

  console.log("step 6");
  // 6. password recovery: sign out, ask for a reset from this browser, follow the emailed link
  await logOut(page);
  await expect(page.getByLabel("Email")).toBeVisible();
  await page.getByRole("button", { name: "Forgot your password?" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Reset password" }).click();
  await expect(page.getByRole("status")).toContainText("If that address has an account");
  await page.goto(await mailLink(request, email, /reset|recover/i));
  await expect(page.getByLabel("New password")).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("New password").fill(NEW_PASSWORD);
  await page.getByRole("button", { name: "Save password" }).click();
  await expect(page.getByLabel("New password")).toHaveCount(0, { timeout: 15_000 });

  console.log("step 7");
  // 7. the old password no longer works, the new one does
  await logOut(page);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Incorrect email or password.");
  await page.getByLabel("Password").fill(NEW_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByLabel("Email")).toHaveCount(0, { timeout: 15_000 });
  expect(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).toEqual([]);
});
