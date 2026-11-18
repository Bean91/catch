import { expect, test } from "@playwright/test";

// Desktop (mouse + keyboard): the Sidebar entry, keyboard-operable sheets, and the confirmations that must hold with a mouse as well as a thumb.

test("desktop: the Clubs sidebar entry opens the hub and a club's tabs are keyboard-operable", async ({ page }) => {
  await page.goto("/?mock=1");
  await page.getByRole("link", { name: "Clubs" }).click();
  await expect(page.getByTestId("clubs-page")).toBeVisible();
  await page.getByTestId("club-link").filter({ hasText: "River Rowing Club" }).click();
  const tablist = page.getByRole("tablist", { name: "Club sections" });
  await expect(tablist).toBeVisible();
  await page.getByTestId("club-tab-calendar").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("club-sessions")).toContainText("Steady 60");
});

test("desktop: Escape cancels an invite sheet and nothing is created", async ({ page }) => {
  await page.goto("/clubs?mock=1");
  await page.getByTestId("club-link").filter({ hasText: "River Rowing Club" }).click();
  await page.getByTestId("club-tab-manage").click();
  await page.getByTestId("invite-new").click();
  await expect(page.getByTestId("invite-sheet")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("invite-sheet")).toBeHidden();
  await expect(page.getByTestId("club-invites").locator("li")).toHaveCount(0);
});

test("desktop: removing a member needs a reason, and Escape leaves them in", async ({ page }) => {
  await page.goto("/clubs?mock=1");
  await page.getByTestId("club-link").filter({ hasText: "River Rowing Club" }).click();
  await page.getByTestId("club-tab-members").click();
  await page.getByTestId("member-row").filter({ hasText: "Tom Catch" }).getByTestId("member-remove").click();
  await expect(page.getByTestId("remove-sheet-submit")).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("remove-sheet")).toBeHidden();
  await expect(page.getByTestId("club-members")).toContainText("Tom Catch");
});

test("desktop: deleting a club shows exactly what is lost and needs a second confirmation", async ({ page }) => {
  await page.goto("/clubs?mock=1&role=owner");
  await page.getByTestId("club-link").filter({ hasText: "River Rowing Club" }).click();
  await page.getByTestId("club-tab-manage").click();
  await page.getByTestId("club-delete").click();
  await expect(page.getByTestId("delete-preview")).toContainText("permanently deletes River Rowing Club");
  await page.getByTestId("club-delete-confirm").click();
  await expect(page.getByTestId("clubs-page")).toBeVisible();
  await expect(page.getByTestId("clubs-mine")).toHaveCount(0);
});

test("desktop: ownership transfer previews before it changes anything", async ({ page }) => {
  await page.goto("/clubs?mock=1&role=owner");
  await page.getByTestId("club-link").filter({ hasText: "River Rowing Club" }).click();
  await page.getByTestId("club-tab-manage").click();
  await page.getByTestId("transfer-select").selectOption({ label: "Sam Admin (admin)" });
  await page.getByTestId("transfer-preview-btn").click();
  await expect(page.getByTestId("transfer-preview")).toContainText("becomes the owner");
  await expect(page.getByTestId("club-header")).toContainText("you are Owner"); // nothing has changed yet
  await page.getByTestId("transfer-confirm").click();
  await expect(page.getByTestId("club-header")).toContainText("you are Admin");
});
