import { expect, test, type Page } from "@playwright/test";

// Session 32 first-run setup at phone width (both mobile projects), all ?mock=1. `onboarding=pending` makes the mock a brand-new
// public account; without it setup is already complete, which every other spec relies on.

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

async function noHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
}

test("a new account lands on setup, can skip every provider, and finishes on the dashboard", async ({ page }) => {
  await page.goto("/?mock=1&onboarding=pending");
  await expect(page).toHaveURL(/\/welcome/);
  await expect(page.getByText("Step 1 of 6")).toBeVisible();
  // The time zone is suggested from the device.
  await expect(page.getByLabel("Your time zone")).toBeVisible();
  await noHorizontalOverflow(page);
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByText("Step 2 of 6")).toBeVisible();
  await expect(page.getByText("Every Concept2 logbook result")).toBeVisible();
  for (const name of ["Skip Concept2"]) {
    const skip = page.getByRole("button", { name });
    if (await skip.count()) await skip.tap();
  }
  await expect(page.getByText("Skipped for now").first()).toBeVisible();
  await noHorizontalOverflow(page);
  await page.getByRole("button", { name: "Next" }).click();

  await expect(page.getByText("Step 3 of 6")).toBeVisible();
  await page.getByRole("button", { name: "Skip", exact: true }).click();

  // Session 34: privacy — everything starts off, and skipping leaves it off.
  await expect(page.getByText("Step 4 of 6")).toBeVisible();
  await expect(page.getByTestId("share-wellness")).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("privacy-lb-state")).toHaveText("Off");
  await noHorizontalOverflow(page);
  await page.getByTestId("privacy-skip").click();

  await expect(page.getByText("Step 5 of 6")).toBeVisible();
  // Never blocked on an import: both ways forward are always enabled.
  await expect(page.getByRole("button", { name: "Go to dashboard" })).toBeEnabled();
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByText("Step 6 of 6")).toBeVisible();
  await expect(page.getByTestId("onboarding-summary")).toContainText("Time zone");
  await page.getByRole("button", { name: "Go to my dashboard" }).click();
  await expect(page).toHaveURL(/\/(\?|$)/);
  await expect(page.getByTestId("onboarding")).toHaveCount(0);
});

test("training basics are checked before saving and can be skipped", async ({ page }) => {
  await page.goto("/welcome?mock=1&onboarding=pending");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByLabel("Max heart rate (bpm)").fill("400");
  await expect(page.getByRole("alert")).toContainText("max HR 120–230");
  await expect(page.getByRole("button", { name: "Save and continue" })).toBeDisabled();
  await page.getByLabel("Max heart rate (bpm)").fill("192");
  await page.getByRole("button", { name: "Save and continue" }).click();
  await expect(page.getByText("Step 4 of 6")).toBeVisible();
});

test("an existing account is never sent to setup", async ({ page }) => {
  await page.goto("/?mock=1");
  await expect(page.getByText("Strain today")).toBeVisible();
  await expect(page).not.toHaveURL(/welcome/);
});

test("a provider sign-in that was refused comes back to setup with a plain sentence, and setup carries on", async ({ page }) => {
  await page.goto("/welcome?mock=1&onboarding=pending&provider=whoop&result=denied");
  await expect(page.getByText("Step 2 of 6")).toBeVisible();
  await expect(page.getByTestId("onboarding-result")).toContainText("wasn't connected");
  await expect(page.getByRole("button", { name: "Next" })).toBeEnabled();
});

async function toPrivacyStep(page: Page) {
  await page.goto("/welcome?mock=1&onboarding=pending");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Skip", exact: true }).click();
  await expect(page.getByText("Step 4 of 6")).toBeVisible();
}

test("privacy in setup: every control starts off and explains itself, nothing switches on without a tap", async ({ page }) => {
  await toPrivacyStep(page);
  await expect(page.getByTestId("privacy-step-intro")).toContainText("starts off");
  await expect(page.getByTestId("privacy-always-private")).toContainText("no public profile");
  for (const key of ["wellness", "workouts", "nutrition", "notes_checkins", "memory", "calendar_library", "photos"]) {
    await expect(page.getByTestId(`share-${key}`)).toHaveAttribute("aria-checked", "false");
  }
  await expect(page.getByTestId("share-wellness")).toBeDisabled(); // nothing on before the disclosure is acknowledged
  await expect(page.getByTestId("privacy-leaderboards")).toContainText("publishes nothing by itself");
  await noHorizontalOverflow(page);
});

test("privacy choices made in setup are kept when going back and forth, and individually", async ({ page }) => {
  await toPrivacyStep(page);
  await page.getByTestId("ai-sharing-agree").tap();
  await page.getByTestId("share-workouts").tap();
  await expect(page.getByTestId("share-workouts")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("share-wellness")).toHaveAttribute("aria-checked", "false"); // one switch, not a blanket consent
  // Leave the step and come back: the choice was saved when tapped (the same endpoint as Settings → Privacy), not held by the step.
  // Resuming on another device reads the same server rows (tests/test_onboarding.py); the mock lives per page load, so no reload here.
  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByText("Step 3 of 6")).toBeVisible();
  await page.getByRole("button", { name: "Skip", exact: true }).click();
  await expect(page.getByText("Step 4 of 6")).toBeVisible();
  await expect(page.getByTestId("share-workouts")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("share-wellness")).toHaveAttribute("aria-checked", "false");
  await page.getByTestId("privacy-continue").click();
  await expect(page.getByText("Step 5 of 6")).toBeVisible();
});

test("joining leaderboards from setup is opt-in, previews nothing, and says it is on", async ({ page }) => {
  await toPrivacyStep(page);
  await page.getByTestId("privacy-lb-join").tap();
  await expect(page.getByTestId("lb-optin")).toBeDisabled(); // needs the explicit tick
  await page.getByTestId("lb-mode-anonymous").tap();
  await page.getByTestId("lb-age13").tap();
  await page.getByTestId("lb-confirm").tap();
  await page.getByTestId("lb-optin").tap();
  await expect(page.getByTestId("privacy-lb-state")).toHaveText("On");
  await expect(page.getByTestId("privacy-leaderboards")).toContainText("nothing is published by joining");
});
