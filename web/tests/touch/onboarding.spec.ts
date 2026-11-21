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
  await expect(page.getByText("Step 1 of 5")).toBeVisible();
  // The time zone is suggested from the device.
  await expect(page.getByLabel("Your time zone")).toBeVisible();
  await noHorizontalOverflow(page);
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByText("Step 2 of 5")).toBeVisible();
  await expect(page.getByText("Every Concept2 logbook result")).toBeVisible();
  for (const name of ["Skip Concept2"]) {
    const skip = page.getByRole("button", { name });
    if (await skip.count()) await skip.tap();
  }
  await expect(page.getByText("Skipped for now").first()).toBeVisible();
  await noHorizontalOverflow(page);
  await page.getByRole("button", { name: "Next" }).click();

  await expect(page.getByText("Step 3 of 5")).toBeVisible();
  await page.getByRole("button", { name: "Skip", exact: true }).click();

  await expect(page.getByText("Step 4 of 5")).toBeVisible();
  // Never blocked on an import: both ways forward are always enabled.
  await expect(page.getByRole("button", { name: "Go to dashboard" })).toBeEnabled();
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByText("Step 5 of 5")).toBeVisible();
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
  await expect(page.getByText("Step 4 of 5")).toBeVisible();
});

test("an existing account is never sent to setup", async ({ page }) => {
  await page.goto("/?mock=1");
  await expect(page.getByText("Strain today")).toBeVisible();
  await expect(page).not.toHaveURL(/welcome/);
});

test("a provider sign-in that was refused comes back to setup with a plain sentence, and setup carries on", async ({ page }) => {
  await page.goto("/welcome?mock=1&onboarding=pending&provider=whoop&result=denied");
  await expect(page.getByText("Step 2 of 5")).toBeVisible();
  await expect(page.getByTestId("onboarding-result")).toContainText("wasn't connected");
  await expect(page.getByRole("button", { name: "Next" })).toBeEnabled();
});
