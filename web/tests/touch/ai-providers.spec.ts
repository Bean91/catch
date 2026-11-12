import { expect, test, type Locator, type Page } from "@playwright/test";

// Settings → AI Providers at the iPhone 13 profile (390px), driven with real touch taps, under both
// mobile projects (real WebKit included). Everything is ?mock=1; the mock lives in memory per page
// load, so flows stay inside the SPA (links and nav taps, never page.goto between steps).

const FULL_KEY = "AIzaSyD-ThisFullKeyMustNeverBeShownAgain-9876";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

async function aboveNav(page: Page, target: Locator) {
  await expect
    .poll(async () => {
      await target.scrollIntoViewIfNeeded();
      return target.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return !!top && (el === top || el.contains(top));
      });
    })
    .toBe(true);
}

const card = (page: Page, id: string) => page.getByTestId(`provider-card-${id}`);

test("all four provider states are distinct words, nothing overflows, no key text is on the page", async ({ page }) => {
  await page.goto("/settings/ai?mock=1");
  await expect(page.getByRole("heading", { name: "AI providers" })).toBeVisible();
  await expect(page.getByTestId("status-anthropic")).toContainText("Connected");
  await expect(page.getByTestId("status-openai")).toContainText("Invalid key");
  await expect(page.getByTestId("status-gemini")).toContainText("Not configured");
  await expect(page.getByTestId("status-ollama")).toContainText("Unavailable");
  await expect(card(page, "anthropic")).toContainText("Active");
  await expect(card(page, "anthropic")).toContainText("…wxyz");
  await noHorizontalOverflow(page);
  expect(await page.locator("body").innerText()).not.toMatch(/sk-ant|AIza|sk-proj/);
});

test("usage is labelled as recorded by Catch and no balance is claimed", async ({ page }) => {
  await page.goto("/settings/ai?mock=1");
  const usage = page.getByTestId("ai-usage");
  await expect(usage).toContainText("tokens");
  await expect(usage).toContainText("cost unknown");
  await expect(usage).toContainText("don't offer a balance");
  expect(await usage.innerText()).not.toMatch(/balance:\s*\$|remaining/i);
});

test("adding a key: the sheet sits above the nav, the key field is a password field, and the key never comes back", async ({ page }) => {
  await page.goto("/settings/ai?mock=1");
  await card(page, "gemini").getByRole("button", { name: "Add key" }).tap();
  const sheet = page.getByTestId("provider-key-sheet");
  await expect(sheet).toBeVisible();
  const input = sheet.getByLabel("API key");
  await expect(input).toHaveAttribute("type", "password");
  await expect(input).toHaveAttribute("autocomplete", "off");
  await input.fill(FULL_KEY);
  const submit = sheet.getByRole("button", { name: "Check and save" });
  await aboveNav(page, submit);
  await submit.tap();
  await expect(sheet).toBeHidden();
  await expect(page.getByTestId("status-gemini")).toContainText("Connected");
  await expect(card(page, "gemini")).toContainText("…9876");
  const text = await page.locator("body").innerText();
  expect(text).not.toContain(FULL_KEY);
  expect(await page.content()).not.toContain(FULL_KEY);
  await noHorizontalOverflow(page);
});

test("a rejected key shows the reason, clears the field and keeps the old state", async ({ page }) => {
  await page.goto("/settings/ai?mock=1");
  await card(page, "openai").getByRole("button", { name: "Replace key" }).tap();
  const sheet = page.getByTestId("provider-key-sheet");
  await sheet.getByLabel("API key").fill("bad-key-1234567890");
  await sheet.getByRole("button", { name: "Check and replace" }).tap();
  await expect(sheet.getByTestId("key-error")).toContainText("rejected");
  await expect(sheet.getByLabel("API key")).toHaveValue("");
  await expect(page.getByTestId("status-openai")).toContainText("Invalid key");
});

test("replacing a key with a good one turns an invalid provider into connected", async ({ page }) => {
  await page.goto("/settings/ai?mock=1");
  await card(page, "openai").getByRole("button", { name: "Replace key" }).tap();
  const sheet = page.getByTestId("provider-key-sheet");
  await sheet.getByLabel("API key").fill("sk-proj-a-valid-looking-key-77aa");
  await sheet.getByRole("button", { name: "Check and replace" }).tap();
  await expect(sheet).toBeHidden();
  await expect(page.getByTestId("status-openai")).toContainText("Connected");
  await expect(card(page, "openai")).toContainText("…77aa");
});

test("removing a key needs confirmation, and says history is kept", async ({ page }) => {
  await page.goto("/settings/ai?mock=1");
  const gem = card(page, "openai");
  await gem.getByRole("button", { name: "Remove key" }).tap();
  const confirm = gem.getByRole("group", { name: "Confirm removing the key" });
  await expect(confirm).toContainText("conversations and coach memory stay");
  await confirm.getByRole("button", { name: "Keep it" }).tap();
  await expect(page.getByTestId("status-openai")).toContainText("Invalid key");
  await gem.getByRole("button", { name: "Remove key" }).tap();
  await gem.getByRole("group", { name: "Confirm removing the key" }).getByRole("button", { name: "Remove key" }).tap();
  await expect(page.getByTestId("status-openai")).toContainText("Not configured");
});

test("test connection reports each provider's real state", async ({ page }) => {
  await page.goto("/settings/ai?mock=1");
  await card(page, "anthropic").getByRole("button", { name: "Test connection" }).tap();
  await expect(page.getByTestId("test-anthropic")).toContainText("Connected — 3 models");
  await card(page, "openai").getByRole("button", { name: "Test connection" }).tap();
  await expect(page.getByTestId("test-openai")).toContainText("rejected");
  await card(page, "ollama").getByRole("button", { name: "Test connection" }).tap();
  await expect(page.getByTestId("test-ollama")).toContainText("Could not reach Ollama");
});

test("switching the active provider changes which card says Active", async ({ page }) => {
  await page.goto("/settings/ai?mock=1");
  await card(page, "openai").getByRole("button", { name: "Make active" }).tap();
  await expect(card(page, "openai")).toContainText("Active");
  await expect(card(page, "anthropic")).not.toContainText("Active");
  await expect(card(page, "anthropic").getByRole("button", { name: "Make active" })).toBeVisible();
});

test("with no active provider the page says AI is off, and photo entry points disappear", async ({ page }) => {
  await page.goto("/settings/ai?mock=1");
  const nav = page.getByRole("navigation").last();
  await nav.getByRole("link", { name: /Fuel/ }).tap();
  await expect(page.getByText("Estimate a meal from a photo")).toBeVisible();

  await nav.getByRole("link", { name: /Settings/ }).tap();
  await page.getByRole("link", { name: /AI providers/ }).tap();
  const a = card(page, "anthropic");
  await a.getByRole("button", { name: "Remove key" }).tap();
  await a.getByRole("group", { name: "Confirm removing the key" }).getByRole("button", { name: "Remove key" }).tap();
  await expect(page.getByTestId("no-active-provider")).toContainText("coach and the photo features are off");
  await nav.getByRole("link", { name: /Fuel/ }).tap();
  await expect(page.getByRole("heading", { name: "Nutrition" })).toBeVisible();
  await expect(page.getByText("Estimate a meal from a photo")).toHaveCount(0);
});

test("Settings shows Whoop with a connect link, the recovery-input choice, and a link to AI providers", async ({ page }) => {
  await page.goto("/settings?mock=1");
  const whoop = page.getByTestId("whoop-controls");
  await expect(whoop.getByRole("link", { name: "Connect Whoop" })).toHaveAttribute("href", "/auth/whoop/start");
  await expect(page.getByRole("radiogroup", { name: "Preferred device" })).toBeVisible();
  await expect(page.getByTestId("ai-provider-summary")).toContainText("Anthropic");
  await noHorizontalOverflow(page);
});

test("the Today recovery details name the source of each input and the calibration state", async ({ page }) => {
  await page.goto("/?mock=1");
  await page.getByRole("button", { name: "Recovery details" }).tap();
  await expect(page.getByTestId("recovery-calibration")).toContainText("Baseline ready");
  const availability = page.getByTestId("recovery-availability");
  await expect(availability).toContainText("Overnight HRV");
  await expect(availability).toContainText("Garmin");
  await expect(availability).toContainText("shown, not scored");
  await noHorizontalOverflow(page);
});
