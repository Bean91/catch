import { expect, test, type Page } from "@playwright/test";

// Text wraps instead of widening the page (a sideways scroll on the phone app). Normal content must fit at 320px, and names and
// messages that come from people or providers must still fit when they are one long unbroken word (a URL, a code, a long name).

const LONG = "Https://developer.apple.com/library/content/documentation/General/Reference/InfoPlistKeyReference/SW73";

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test.use({ viewport: { width: 320, height: 700 } });
test.beforeEach(async ({ page }) => page.emulateMedia({ reducedMotion: "reduce" }));

for (const path of ["/", "/calendar", "/workouts", "/workouts/1", "/tests", "/trends", "/body", "/nutrition", "/coach", "/library", "/settings", "/settings/connections", "/settings/privacy", "/clubs", "/leaderboards"]) {
  test(`${path} fits a 320px screen`, async ({ page }) => {
    await page.goto(`${path}?mock=1`);
    await page.waitForLoadState("networkidle");
    await noSidewaysScroll(page);
  });
}

async function lengthen(page: Page, selector: string) {
  await page.locator(selector).first().waitFor();
  await page.locator(selector).evaluateAll((els, long) => els.forEach((el) => (el.textContent = long)), LONG);
}

test("a one-word template name wraps", async ({ page }) => {
  await page.goto("/library?mock=1");
  await lengthen(page, "[data-testid=template-card] span.font-medium");
  await noSidewaysScroll(page);
});

test("a one-word workout title wraps", async ({ page }) => {
  await page.goto("/workouts/1?mock=1");
  await lengthen(page, "h1");
  await noSidewaysScroll(page);
});

test("a long provider scope wraps", async ({ page }) => {
  await page.goto("/settings/connections?mock=1");
  await lengthen(page, "dd");
  await noSidewaysScroll(page);
});

test("an error message carrying a URL wraps", async ({ page }) => {
  await page.goto("/library?mock=1");
  await page.evaluate((long) => {
    const p = document.createElement("p");
    p.className = "text-sm text-band-red-text";
    p.textContent = `You are missing a setting. Learn more: ${long}`;
    const host = document.createElement("div");
    host.className = "flex flex-col items-center";
    host.appendChild(p);
    document.querySelector("main")!.prepend(host);
  }, LONG);
  await noSidewaysScroll(page);
});

test("the Add piece sheet fits, including its side-by-side totals and a long error", async ({ page }) => {
  await page.goto("/workouts/6?mock=1");
  await expect(async () => {
    await page.getByRole("button", { name: "Add piece" }).click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 2000 });
  }).toPass({ timeout: 20_000 });
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Type or paste splits" }).click();
  await expect(dialog.getByText("Total time, if different")).toBeVisible();
  await noSidewaysScroll(page);
  const sticksOut = () => dialog.evaluate((d) => d.scrollWidth - d.clientWidth);
  expect(await sticksOut()).toBeLessThanOrEqual(0);
  await dialog.evaluate((d, long) => {
    const p = document.createElement("p");
    p.className = "text-sm text-band-red-text";
    p.textContent = `Camera failed. Learn more: ${long}`;
    d.querySelector("div")!.appendChild(p);
  }, LONG);
  expect(await sticksOut()).toBeLessThanOrEqual(0);
  await noSidewaysScroll(page);
});
