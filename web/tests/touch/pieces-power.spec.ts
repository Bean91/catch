import { expect, test } from "@playwright/test";

// Session 34 (?mock=1): watts come from the server's preview — the browser holds no power formula (the mock answers with precomputed
// constants for a few paces, as the server would). A rowing split's watts are shown as calculated; a contradictory typed value is flagged
// and the split wins; a bike's power is never calculated from pace; weight-adjusted power is shown beside the watts with its unit.

async function openAddPiece(page: import("@playwright/test").Page) {
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

test("rowing watts are calculated from each split by the server, and the average from the average split", async ({ page }) => {
  await openAddPiece(page);
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox").selectOption("2000m");
  await dialog.getByRole("button", { name: "Type or paste splits" }).click();
  await expect(dialog.getByRole("spinbutton").first()).toHaveValue("500"); // the template has loaded, so the paste merges onto it
  await dialog.getByPlaceholder(/1:36.8/).fill("1:45.0 30 / 1:45.0 30 / 1:45.0 30 / 1:45.0 30");
  await dialog.getByRole("button", { name: "Apply paste" }).click();
  await dialog.getByRole("button", { name: "Review" }).click();
  await expect(dialog.getByRole("columnheader", { name: "Watts (from split)" })).toBeVisible();
  await expect(dialog.getByLabel("Split 1 watts")).toHaveAttribute("placeholder", "302"); // 2.8 / (105/500)^3 = 302.3 W
  await expect(dialog.getByTestId("piece-power-summary")).toContainText("302 W — calculated from the 1:45.0");
  await expect(dialog.getByTestId("watts-help")).toContainText("calculated from each split");

  await dialog.getByLabel("Split 1 watts").fill("250"); // contradicts the split
  await expect(dialog.getByText(/250 W doesn't match the split/)).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Save anyway" })).toBeVisible();
  await dialog.getByLabel("Split 1 watts").fill("302"); // the PM5's own rounding is fine
  await expect(dialog.getByRole("button", { name: "Save piece" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("a bike piece never gets watts from its pace", async ({ page }) => {
  await openAddPiece(page);
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("radio", { name: /Bike/ }).click();
  await dialog.getByRole("combobox").selectOption("2000m");
  await dialog.getByRole("button", { name: "Type or paste splits" }).click();
  await expect(dialog.getByRole("spinbutton").first()).toHaveValue("1000");
  await dialog.getByPlaceholder(/1:36.8/).fill("1:40.0 90 / 1:40.0 90");
  await dialog.getByRole("button", { name: "Apply paste" }).click();
  await dialog.getByRole("button", { name: "Review" }).click();
  await expect(dialog.getByRole("columnheader", { name: "Watts", exact: true })).toBeVisible();
  await expect(dialog.getByLabel("Split 1 watts")).toHaveAttribute("placeholder", "");
  await expect(dialog.getByTestId("piece-power-summary")).toContainText("a bike's power isn't calculated from pace");
  await expect(dialog.getByTestId("watts-help")).toContainText("never calculated from pace");
});

test("a saved piece shows weight-adjusted power beside its watts, with the unit and what it means", async ({ page }) => {
  await page.goto("/tests/piece/1?mock=1");
  const mass = page.getByTestId("mass-power").first(); // the page header; the embedded piece card shows the compact version too
  await expect(mass).toContainText("W/kg²ᐟ³");
  await expect(page.getByTestId("mass-power-wap").first()).toHaveText("20.14");
  await expect(mass).toContainText("4.69 W/kg");
  await expect(mass).toContainText("371 W");
  await expect(mass).toContainText("body mass^⅔");
  await expect(mass).toContainText("79.0 kg");
});
