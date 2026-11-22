import { expect, test } from "@playwright/test";

// Session 33, Part D on phones (both mobile projects — the WebKit one is the only coverage of iOS's createImageBitmap/toBlob resize).
// ?mockphoto=totals makes the mock PM5 reading return totals with no splits table: the screen that used to make a piece unsaveable.
// The same flow against the real backend is web/tests/gym-offline/piece-photo.spec.ts.

const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR4nGOoiDqBFTEMLQkA+RFmgRtoVlEAAAAASUVORK5CYII=", "base64");

test("a totals-only PM5 photo becomes a saved piece with its photo, which can be replaced and removed", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/workouts/6?mock=1&mockphoto=totals");
  await expect(page.getByRole("heading", { name: "Pieces" })).toBeVisible();
  await expect(async () => {
    await page.getByRole("button", { name: "Add piece" }).click();
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 2000 });
  }).toPass({ timeout: 20_000 });
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Take or choose a photo of the PM5 screen" })).toBeVisible();
  await dialog.locator('input[type="file"]').setInputFiles({ name: "pm5.png", mimeType: "image/png", buffer: PNG });

  await expect(dialog.getByTestId("piece-photo-preview")).toBeVisible();
  await expect(dialog.getByRole("combobox")).toHaveValue("5000m");
  await expect(dialog.getByLabel("Total distance (m)")).toHaveValue("5000");
  await expect(dialog.getByText("No splits — the piece is saved from its totals.")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const save = dialog.getByRole("button", { name: "Save piece" });
  await save.scrollIntoViewIfNeeded();
  await save.click();
  await expect(dialog).toBeHidden();

  const card = page.locator("div.rounded-md.border", { has: page.getByText("5000m", { exact: true }) }).last();
  await card.getByRole("button", { name: "View photo" }).click();
  const img = card.getByRole("img", { name: "PM5 screen" });
  await expect(img).toBeVisible();
  await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);

  await card.locator('input[type="file"]').setInputFiles({ name: "again.png", mimeType: "image/png", buffer: PNG });
  await expect(card.getByRole("img", { name: "PM5 screen" })).toBeVisible();
  await card.getByRole("button", { name: "Remove photo" }).click();
  await expect(card.getByRole("button", { name: "Add photo" })).toBeVisible();
});
