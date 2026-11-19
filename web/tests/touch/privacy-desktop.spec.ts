import { expect, test } from "@playwright/test";

test("desktop: privacy controls are reachable with the mouse and the keyboard", async ({ page }) => {
  await page.goto("/settings/privacy?mock=1");
  await page.getByTestId("ai-sharing-agree").check();
  await page.getByTestId("share-memory").click();
  await expect(page.getByTestId("share-memory")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("share-memory").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("share-memory")).toHaveAttribute("aria-checked", "false");
  await page.getByTestId("delete-notes_checkins").click();
  await page.getByTestId("confirm-delete-notes_checkins").click();
  await expect(page.getByTestId("delete-message")).toContainText("Removed");
});
