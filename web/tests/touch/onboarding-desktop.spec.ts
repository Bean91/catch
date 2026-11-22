import { expect, test } from "@playwright/test";

test("setup reads well at desktop width and can be left at any step", async ({ page }) => {
  await page.goto("/?mock=1&onboarding=pending");
  await expect(page).toHaveURL(/\/welcome/);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Step 2 of 6")).toBeVisible();
  await page.getByRole("button", { name: /Skip setup/ }).click();
  await expect(page).not.toHaveURL(/welcome/);
});

test("the privacy step fits at desktop width and Continue keeps everything off", async ({ page }) => {
  await page.goto("/welcome?mock=1&onboarding=pending");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Skip", exact: true }).click();
  await expect(page.getByText("Your privacy")).toBeVisible();
  await page.getByTestId("privacy-continue").click();
  await expect(page.getByText("Step 5 of 6")).toBeVisible();
});
