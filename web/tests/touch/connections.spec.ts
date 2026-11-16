import { expect, test, type Locator, type Page } from "@playwright/test";

// Settings → Connections at the iPhone 13 profile (390px), real touch taps, under both mobile projects. Everything is ?mock=1; the mock
// is in memory per page load, so flows stay inside the SPA (links and taps, never page.goto between steps).

const FULL_KEY = "garmin-personal-key-MUST-NEVER-BE-SHOWN-AGAIN-9f3a77";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

async function noHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
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

const card = (page: Page, id: string) => page.getByTestId(`connection-${id}`);

test("every provider shows a distinct status word, honest limits, and nothing overflows", async ({ page }) => {
  await page.goto("/settings/connections?mock=1");
  await expect(page.getByRole("heading", { name: "Connections" })).toBeVisible();
  await expect(page.getByTestId("conn-status-garmin")).toContainText("Connected");
  await expect(page.getByTestId("conn-status-withings")).toContainText("Reconnect needed");
  await expect(page.getByTestId("conn-status-concept2")).toContainText("Not connected");
  await expect(page.getByTestId("conn-status-whoop")).toContainText("importing history");
  await expect(page.getByTestId("conn-history-whoop")).toContainText("Importing from");
  await expect(page.getByTestId("conn-recovery-withings")).toContainText("Choose Reconnect");
  await noHorizontalOverflow(page);
});

test("Garmin says it uses your own key, quotes Garmin's wording, and never asks for a password or Developer Program credentials", async ({ page }) => {
  await page.goto("/settings/connections?mock=1");
  const garmin = card(page, "garmin");
  await expect(page.getByTestId("conn-note-garmin")).toContainText("a key you create yourself");
  await expect(page.getByTestId("conn-note-garmin")).toContainText("not intended for commercial applications serving multiple end users");
  await garmin.getByText("What Catch can and can't do with Garmin").tap();
  await expect(page.getByTestId("conn-limits-garmin")).toContainText("never your Garmin password");
  await expect(page.getByTestId("conn-limits-garmin")).toContainText("Skin temperature");
  const text = (await page.locator("body").innerText()).toLowerCase();
  expect(text).not.toContain("developer program credentials");
  expect(text).not.toContain("consumer key");
  await noHorizontalOverflow(page);
});

test("adding a Garmin key: masked field, validated, never shown again, sheet clears on failure", async ({ page }) => {
  await page.goto("/settings/connections?mock=1");
  await card(page, "garmin").getByRole("button", { name: "Replace key" }).tap();
  const sheet = page.getByTestId("credential-sheet");
  await expect(sheet).toBeVisible();
  const input = sheet.getByLabel("Personal API key");
  await expect(input).toHaveAttribute("type", "password");
  await expect(input).toHaveAttribute("autocomplete", "off");
  await aboveNav(page, sheet.getByRole("button", { name: "Check and replace" }));

  await input.fill("bad-key-that-garmin-rejects");
  await sheet.getByRole("button", { name: "Check and replace" }).tap();
  await expect(page.getByTestId("credential-error")).toContainText("Garmin rejected the key");
  await expect(input).toHaveValue("");

  await input.fill(FULL_KEY);
  await sheet.getByLabel("Key expires on (optional)").fill("2027-05-01");
  await sheet.getByRole("button", { name: "Check and replace" }).tap();
  await expect(sheet).toBeHidden();
  await expect(card(page, "garmin")).toContainText("Key …9f3a".replace("9f3a", FULL_KEY.slice(-4)));
  await expect(card(page, "garmin")).toContainText("2027-05-01");
  expect(await page.locator("body").innerText()).not.toContain(FULL_KEY);
  expect(await page.content()).not.toContain(FULL_KEY);
  await noHorizontalOverflow(page);
});

test("a short key is never echoed, not even its last four characters", async ({ page }) => {
  await page.goto("/settings/connections?mock=1");
  await card(page, "concept2").getByRole("button", { name: "Use a personal token instead" }).tap();
  const sheet = page.getByTestId("credential-sheet");
  await sheet.getByLabel("Personal access token").fill("short-tok");
  await sheet.getByRole("button", { name: "Check and save" }).tap();
  await expect(sheet).toBeHidden();
  await expect(card(page, "concept2")).toContainText("Token saved");
  expect(await page.content()).not.toContain("short-tok");
});

test("Reconnect for a sign-in provider and Test / Sync now report plainly", async ({ page }) => {
  await page.goto("/settings/connections?mock=1");
  const withings = card(page, "withings");
  await withings.getByRole("button", { name: "Test connection" }).tap();
  await expect(page.getByTestId("conn-test-withings")).toContainText("refused the saved authorization");
  await withings.getByRole("button", { name: "Reconnect" }).tap();
  await expect(page.getByTestId("conn-status-withings")).toContainText("Connected");
  await card(page, "whoop").getByRole("button", { name: "Sync now" }).tap();
  await expect(page.getByTestId("conn-notice-whoop")).toContainText("Synced");
});

test("disconnect is confirmed inline, says what stays, and returns the card to not connected", async ({ page }) => {
  await page.goto("/settings/connections?mock=1");
  const garmin = card(page, "garmin");
  await garmin.getByRole("button", { name: "Disconnect" }).tap();
  const confirm = garmin.getByRole("group", { name: "Confirm disconnecting Garmin" });
  await expect(confirm).toContainText("Everything already imported stays");
  await expect(confirm).toContainText("delete the key in Garmin Connect");
  await confirm.getByRole("button", { name: "Keep it" }).tap();
  await expect(page.getByTestId("conn-status-garmin")).toContainText("Connected");
  await garmin.getByRole("button", { name: "Disconnect" }).tap();
  await garmin.getByRole("group", { name: "Confirm disconnecting Garmin" }).getByRole("button", { name: "Disconnect" }).tap();
  await expect(page.getByTestId("conn-status-garmin")).toContainText("Not connected");
  await expect(garmin.getByRole("button", { name: "Add your Garmin key" })).toBeVisible();
});

test("the OAuth return lands on the page with a plain result notice", async ({ page }) => {
  await page.goto("/settings/connections?mock=1&provider=whoop&result=denied");
  await expect(page.getByTestId("connection-result")).toContainText("access wasn't granted");
  await page.goto("/settings/connections?mock=1&provider=whoop&result=connected");
  await expect(page.getByTestId("connection-result")).toContainText("Whoop connected.");
});
