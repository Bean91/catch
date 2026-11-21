import { expect, test } from "@playwright/test";

test("setup reads well at desktop width and can be left at any step", async ({ page }) => {
  await page.goto("/?mock=1&onboarding=pending");
  await expect(page).toHaveURL(/\/welcome/);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Step 2 of 5")).toBeVisible();
  await page.getByRole("button", { name: /Skip setup/ }).click();
  await expect(page).not.toHaveURL(/welcome/);
});
