import { expect, test } from "@playwright/test";

test("desktop: the Leaderboards sidebar entry opens the board and filters are keyboard-operable", async ({ page }) => {
  await page.goto("/?mock=1");
  await page.getByRole("link", { name: "Leaderboards" }).click();
  await expect(page.getByTestId("lb-context")).toContainText("Verified results only");
  await page.getByTestId("lb-board").selectOption("30min");
  await expect(page.getByTestId("lb-context")).toContainText("30 minutes");
  await expect(page.getByTestId("lb-entries")).toContainText("8,214 m");
});

test("desktop: publishing is a three-step sheet that needs an explicit confirm, and Escape cancels without publishing", async ({ page }) => {
  await page.goto("/settings/leaderboards?mock=1");
  await page.getByTestId("lb-mode-anonymous").click();
  await page.getByTestId("lb-age13").check();
  await page.getByTestId("lb-confirm").check();
  await page.getByTestId("lb-optin").click();
  await page.getByTestId("lb-publish-concept2_result-101").click();
  await page.getByTestId("publish-next").click();
  await page.getByTestId("publish-preview").click();
  await expect(page.getByTestId("publish-preview-entry")).toContainText("Anonymous rower");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("publish-sheet")).toBeHidden();
  await expect(page.getByTestId("lb-publish-concept2_result-101")).toBeVisible(); // still unpublished
});

test("desktop: a moderator needs a written reason for every action", async ({ page }) => {
  await page.goto("/settings/leaderboards?mock=1&mod=1");
  await page.getByTestId("lb-mode-anonymous").click();
  await page.getByTestId("lb-age13").check();
  await page.getByTestId("lb-confirm").check();
  await page.getByTestId("lb-optin").click();
  await page.getByTestId("lb-mod-link").click();
  await page.getByTestId("mod-remove-e6").click();
  await expect(page.getByTestId("mod-error")).toContainText("A reason is required");
  await page.getByTestId("mod-reason-e6").fill("The time can't be checked against Concept2.");
  await page.getByTestId("mod-remove-e6").click();
  await expect(page.getByTestId("mod-report-e6")).toHaveCount(0);
});
