import { expect, test } from "@playwright/test";

test("desktop: provider cards, keyboard-reachable key sheet, and no key echo", async ({ page }) => {
  await page.goto("/settings/ai?mock=1");
  await expect(page.getByTestId("status-anthropic")).toContainText("Connected");
  await page.getByTestId("provider-card-gemini").getByRole("button", { name: "Add key" }).click();
  const sheet = page.getByTestId("provider-key-sheet");
  await expect(sheet).toBeVisible();
  await sheet.getByLabel("API key").fill("AIzaDesktopKeyThatMustNotComeBack-5555");
  await page.keyboard.press("Enter");
  await expect(sheet).toBeHidden();
  await expect(page.getByTestId("provider-card-gemini")).toContainText("…5555");
  expect(await page.content()).not.toContain("AIzaDesktopKeyThatMustNotComeBack");
});
