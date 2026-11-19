import { expect, test, type Page } from "@playwright/test";

// Settings → Privacy at the iPhone 13 profile, real touch taps, both mobile projects. All ?mock=1; the mock lives in memory per page load.

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("the privacy page opens from Settings, fits the screen, and every AI category starts off", async ({ page }) => {
  await page.goto("/settings?mock=1");
  await page.getByTestId("settings-privacy").tap();
  await expect(page.getByRole("heading", { name: "Privacy" })).toBeVisible();
  const sharing = page.getByTestId("ai-sharing");
  await expect(sharing).toBeVisible();
  for (const key of ["wellness", "workouts", "nutrition", "notes_checkins", "memory", "calendar_library", "photos"]) {
    await expect(page.getByTestId(`share-${key}`)).toHaveAttribute("aria-checked", "false");
  }
  await noHorizontalOverflow(page);
});

test("nothing can be switched on until the disclosure is acknowledged, and a young age needs a guardian tick", async ({ page }) => {
  await page.goto("/settings/privacy?mock=1");
  await expect(page.getByTestId("share-wellness")).toBeDisabled();
  await page.getByTestId("ai-sharing-agree").tap();
  await page.getByTestId("share-nutrition").tap();
  await expect(page.getByTestId("share-nutrition")).toHaveAttribute("aria-checked", "true");

  await page.getByLabel("Age (optional)").selectOption("u16");
  await page.getByTestId("share-wellness").tap();
  await expect(page.getByTestId("ai-sharing-error")).toContainText("parent or guardian");
  await expect(page.getByTestId("share-wellness")).toHaveAttribute("aria-checked", "false");
  await page.getByTestId("guardian-ack").tap();
  await page.getByTestId("share-wellness").tap();
  await expect(page.getByTestId("share-wellness")).toHaveAttribute("aria-checked", "true");

  await page.getByTestId("ai-sharing-withdraw").tap();
  await expect(page.getByTestId("share-wellness")).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("share-nutrition")).toHaveAttribute("aria-checked", "false");
});

test("deleting a category is a two-step action and updates the count", async ({ page }) => {
  await page.goto("/settings/privacy?mock=1");
  const card = page.getByTestId("delete-data-card");
  await expect(card).toContainText("Coach conversations (14)");
  await page.getByTestId("delete-conversations").tap();
  await expect(page.getByRole("alertdialog", { name: "Delete Coach conversations" })).toBeVisible();
  await page.getByTestId("confirm-delete-conversations").tap();
  await expect(page.getByTestId("delete-message")).toContainText("Removed 14 items");
  await expect(card).toContainText("Coach conversations (0)");
  await expect(page.getByTestId("delete-conversations")).toBeDisabled();
});

test("an app's access can be ended, and the export is offered", async ({ page }) => {
  await page.goto("/settings/privacy?mock=1");
  await expect(page.getByTestId("connected-apps")).toContainText("Laptop (Claude Desktop)");
  await expect(page.getByTestId("connected-apps")).toContainText("read only");
  await page.getByTestId("revoke-token-1").tap();
  await expect(page.getByTestId("connected-apps")).not.toContainText("Laptop (Claude Desktop)");
  await page.getByTestId("end-grant-g1").tap();
  await expect(page.getByTestId("connected-apps")).toContainText("No apps are connected.");
  await expect(page.getByTestId("export-button")).toBeVisible();
  await expect(page.getByTestId("visibility-card")).toContainText("2 published results");
  await noHorizontalOverflow(page);
});

test("the legal drafts open, say they are drafts, and fit the screen", async ({ page }) => {
  await page.goto("/legal/privacy-policy?mock=1");
  await expect(page.getByTestId("legal-banner")).toContainText("NOT LEGALLY REVIEWED");
  await expect(page.getByRole("heading", { name: "Privacy policy — DRAFT" })).toBeVisible();
  await noHorizontalOverflow(page);
  await page.getByRole("link", { name: "AI data sharing" }).tap();
  await expect(page.getByRole("heading", { name: /What is shared with AI providers/ })).toBeVisible();
  await page.getByRole("link", { name: "Provider integrations" }).tap();
  await expect(page.getByRole("heading", { name: /Provider integrations/ })).toBeVisible();
  await noHorizontalOverflow(page);
});

test("an app asks to connect: the person sees who and what, and nothing is granted until Allow", async ({ page }) => {
  await page.goto("/oauth/consent?mock=1&req=mock");
  const consent = page.getByTestId("oauth-consent");
  await expect(consent).toContainText("Claude Desktop");
  await expect(consent).toContainText("claude.ai");
  await expect(page.getByTestId("consent-write")).not.toBeChecked();
  await noHorizontalOverflow(page);
  await page.getByTestId("consent-deny").tap();
  await expect(page).toHaveURL(/denied=1/);
});

test("a stale consent link is explained and grants nothing", async ({ page }) => {
  await page.goto("/oauth/consent?mock=1");
  await expect(page.getByTestId("consent-invalid")).toContainText("isn't valid any more");
});

test("an OAuth-connected app is listed in Privacy and its access can be ended", async ({ page }) => {
  await page.goto("/settings/privacy?mock=1");
  await expect(page.getByTestId("oauth-grants")).toContainText("Claude Desktop");
  await page.getByTestId("end-grant-g1").tap();
  await expect(page.getByTestId("oauth-grants")).not.toContainText("Claude Desktop");
});
