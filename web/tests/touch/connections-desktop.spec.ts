import { expect, test } from "@playwright/test";

test("desktop: keyboard-reachable key sheet, Enter submits, and the key never comes back", async ({ page }) => {
  await page.goto("/settings/connections?mock=1");
  await expect(page.getByTestId("conn-status-garmin")).toContainText("Connected");
  await page.getByTestId("connection-garmin").getByRole("button", { name: "Replace key" }).click();
  const sheet = page.getByTestId("credential-sheet");
  await expect(sheet).toBeVisible();
  await sheet.getByLabel("Personal API key").fill("desktop-garmin-key-must-not-come-back-4242");
  await page.keyboard.press("Enter");
  await expect(sheet).toBeHidden();
  await expect(page.getByTestId("connection-garmin")).toContainText("…4242");
  expect(await page.content()).not.toContain("desktop-garmin-key-must-not-come-back");
});

test("desktop: Settings lists the sources and links to Connections", async ({ page }) => {
  await page.goto("/settings?mock=1");
  await page.getByRole("link", { name: "Connect, replace a key or disconnect" }).click();
  await expect(page.getByRole("heading", { name: "Connections" })).toBeVisible();
});
