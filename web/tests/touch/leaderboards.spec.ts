import { expect, test, type Locator, type Page } from "@playwright/test";

// Leaderboards at the iPhone 13 profile (390px), real touch taps, under both mobile projects. Everything is ?mock=1; the mock is in memory per
// page load, so each flow stays inside the SPA (links and taps, never page.goto between steps).

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

test("a board states its ranking context, ranks ties together, and shows each state as a glyph and a word", async ({ page }) => {
  await page.goto("/leaderboards?mock=1");
  await expect(page.getByRole("heading", { name: "Leaderboards" })).toBeVisible();
  await expect(page.getByTestId("lb-context")).toContainText("2,000 m · Verified results only · 4 athletes");
  const ranks = await page.getByTestId("lb-entries").locator('[aria-label^="Rank"]').allInnerTexts();
  expect(ranks).toEqual(["1", "2", "2", "4"]); // standard competition ranking: a tie shares a rank
  await expect(page.getByTestId("lb-entries").getByTestId("verification-verified").first()).toContainText("Verified");
  await expect(page.getByTestId("lb-unverified")).toHaveCount(0); // never mixed in by default
  await noHorizontalOverflow(page);
});

test("including unverified results lists them separately, labelled, below the verified ones", async ({ page }) => {
  await page.goto("/leaderboards?mock=1");
  await page.getByTestId("lb-verification").selectOption("include_unverified");
  const section = page.getByTestId("lb-unverified");
  await expect(section).toContainText("never above a verified result", { ignoreCase: true });
  await expect(section.getByTestId("verification-provider_linked")).toContainText("Provider-linked");
  await expect(section.getByTestId("verification-unverified")).toContainText("Unverified");
  await expect(page.getByTestId("lb-context")).toContainText("others listed separately");
});

test("age filter narrows the board and says so", async ({ page }) => {
  await page.goto("/leaderboards?mock=1");
  await page.getByTestId("lb-age").selectOption("U19");
  await expect(page.getByTestId("lb-context")).toContainText("Age U19");
  await expect(page.getByTestId("lb-entries").locator("li")).toHaveCount(1);
});

test("reporting a result needs no account detail and confirms what happens next", async ({ page }) => {
  await page.goto("/leaderboards?mock=1");
  await page.getByTestId("report-e4").tap();
  const sheet = page.getByTestId("report-sheet");
  await expect(sheet).toBeVisible();
  await aboveNav(page, sheet.getByTestId("report-send"));
  await sheet.getByTestId("report-send").tap();
  await expect(page.getByTestId("report-done")).toContainText("A moderator will look at this");
});

test("the opt-in flow: handle, confirmation, then publish through a preview that is exactly what goes public", async ({ page }) => {
  await page.goto("/leaderboards?mock=1");
  await page.getByTestId("lb-join").tap();
  await expect(page.getByTestId("verification-explainer")).toContainText("not that Catch guarantees who rowed it");
  const optin = page.getByTestId("lb-optin");
  await expect(optin).toBeDisabled(); // nothing happens without the explicit confirmation
  await page.getByTestId("lb-handle").fill("River Otter 2");
  await page.getByTestId("lb-age13").tap();
  await page.getByTestId("lb-confirm").tap();
  await optin.tap();

  const row = page.getByTestId("lb-result-concept2_result-101");
  await expect(row).toBeVisible();
  await expect(row.getByTestId("verification-verified")).toBeVisible();
  await row.getByTestId("lb-publish-concept2_result-101").tap();

  const sheet = page.getByTestId("publish-sheet");
  await expect(sheet.getByTestId("verification-meaning")).toContainText("Fetched through your own Concept2 account");
  await sheet.getByTestId("publish-next").tap();
  await expect(sheet.getByTestId("publish-precision")).toHaveValue("none"); // dates are off unless you turn them on
  await sheet.getByTestId("publish-precision").selectOption("year");
  await aboveNav(page, sheet.getByTestId("publish-preview"));
  await sheet.getByTestId("publish-preview").tap();
  const preview = sheet.getByTestId("publish-preview-entry");
  await expect(preview).toContainText("River Otter 2");
  await expect(preview).toContainText("2026");
  await expect(preview).not.toContainText("2026-10");
  await aboveNav(page, sheet.getByTestId("publish-confirm"));
  await sheet.getByTestId("publish-confirm").tap();
  await expect(page.getByTestId("publish-done")).toBeVisible();
  await page.getByRole("button", { name: "Close" }).tap();
  await expect(row.getByTestId("lb-status-concept2_result-101")).toContainText("Public");

  // Take it down: an inline confirmation, then it is gone and the history says why.
  await row.getByTestId("lb-takedown-concept2_result-101").tap();
  await row.getByTestId("lb-takedown-confirm-concept2_result-101").tap();
  await expect(row.getByTestId("lb-publish-concept2_result-101")).toBeVisible();
  await expect(page.getByTestId("lb-events")).toContainText("Withdrawn by the athlete");
  await noHorizontalOverflow(page);
});

test("the public profile preview shows exactly what others see, and anonymous hides the handle", async ({ page }) => {
  await page.goto("/settings/leaderboards?mock=1");
  await page.getByTestId("lb-mode-anonymous").tap();
  await page.getByTestId("lb-age13").tap();
  await page.getByTestId("lb-confirm").tap();
  await page.getByTestId("lb-optin").tap();
  await page.getByTestId("lb-publish-concept2_result-101").tap();
  const sheet = page.getByTestId("publish-sheet");
  await sheet.getByTestId("publish-next").tap();
  await sheet.getByTestId("publish-preview").tap();
  await sheet.getByTestId("publish-confirm").tap();
  await page.getByRole("button", { name: "Close" }).tap();
  await page.getByTestId("lb-profile-toggle").tap();
  const profile = page.getByTestId("lb-profile-preview");
  await expect(profile).toContainText("Anonymous rower");
  await expect(profile).toContainText("6:34.2");
  await noHorizontalOverflow(page);
});

test("opting out is an inline confirmation and takes everything down", async ({ page }) => {
  await page.goto("/settings/leaderboards?mock=1");
  await page.getByTestId("lb-mode-anonymous").tap();
  await page.getByTestId("lb-age13").tap();
  await page.getByTestId("lb-confirm").tap();
  await page.getByTestId("lb-optin").tap();
  await page.getByTestId("lb-optout").tap();
  await page.getByTestId("lb-optout-confirm").tap();
  await expect(page.getByTestId("lb-join-form")).toBeVisible();
});

test("an athlete's page shows only public results", async ({ page }) => {
  await page.goto("/leaderboards?mock=1");
  await page.getByRole("link", { name: "River Otter" }).first().tap();
  await expect(page.getByTestId("lb-athlete-name")).toContainText("River Otter");
  const text = (await page.locator("body").innerText()).toLowerCase();
  for (const word of ["hrv", "sleep score", "recovery score", "weight kg", "calories"]) expect(text).not.toContain(word);
});
