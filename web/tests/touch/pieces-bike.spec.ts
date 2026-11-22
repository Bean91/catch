import { expect, test } from "@playwright/test";

// Session 33: a bike piece next to rowing ones (?mock=1). The unit is the machine's own — /1000m — in every label and figure, the
// rate column is cadence in rpm, and the rowing-only rate-capped type isn't offered.

async function openAddPiece(page: import("@playwright/test").Page) {
  // Under a full parallel run the first tap can land before the page is interactive; retry until the dialog is open.
  await expect(async () => {
    await page.getByRole("button", { name: "Add piece" }).click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 2000 });
  }).toPass({ timeout: 20_000 });
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/workouts/6?mock=1");
  await expect(page.getByRole("heading", { name: "Pieces" })).toBeVisible();
});

test("a typed bike piece is per 1000 m from the template to the saved card", async ({ page }) => {
  await openAddPiece(page);
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("radio", { name: /Bike/ }).click();
  await expect(dialog.getByRole("radio", { name: /Bike/ })).toHaveAttribute("aria-checked", "true");
  await expect(dialog.getByRole("combobox").locator("option", { hasText: "30min_r20" })).toHaveCount(0);
  await dialog.getByRole("combobox").selectOption("2000m");
  await dialog.getByRole("button", { name: "Type or paste splits" }).click();

  await expect(dialog.getByRole("columnheader", { name: "Split /1000m" })).toBeVisible();
  await expect(dialog.getByRole("spinbutton").first()).toHaveValue("1000"); // template rows are per 1000 m
  await expect(dialog.getByRole("columnheader", { name: "Cadence (rpm)" })).toBeVisible();
  await dialog.getByPlaceholder(/1:36.8/).fill("1:40.0 90 / 1:42.0 92");
  await dialog.getByRole("button", { name: "Apply paste" }).click();
  await dialog.getByRole("button", { name: "Review" }).click();
  await expect(dialog.getByText("Bike piece")).toBeVisible();
  await dialog.getByRole("button", { name: "Save piece" }).click();
  await expect(dialog).toBeHidden();

  const card = page.locator("div.rounded-md.border", { has: page.getByText("Bike", { exact: true }) }).last();
  await expect(card).toContainText("Avg split /1000m");
  await expect(card).toContainText("1:41.0"); // 202 s over 2 km, per 1000 m
  await expect(card).toContainText("Avg cadence (rpm)");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("rowing stays the default, at /500m", async ({ page }) => {
  await openAddPiece(page);
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("radio", { name: /Rowing erg/ })).toHaveAttribute("aria-checked", "true");
  await dialog.getByRole("button", { name: "Type or paste splits" }).click();
  await expect(dialog.getByRole("columnheader", { name: "Split /500m" })).toBeVisible();
  await expect(dialog.getByRole("columnheader", { name: "Rate (spm)" })).toBeVisible();
});
