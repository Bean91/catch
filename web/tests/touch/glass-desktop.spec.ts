import { expect, test } from "@playwright/test";

// Session 37 (DESIGN.md "Mobile glass"): glass is for the phone/tablet layout only. At lg and up the desktop design must be exactly
// session 35's: no glass blur, cards on the opaque --surface, the page's own gradient, no Reduce transparency switch. (The full
// before/after computed-style comparison is recorded in PLAN.md; this is the standing guard against a rule leaking out of glass.css.)

const ROUTES = ["/", "/trends", "/calendar?view=month", "/settings", "/workouts/1", "/lab", "/coach"];

for (const width of [1280, 1024]) {
  for (const scheme of ["dark", "light"] as const) {
    test(`no glass at ${width}px (${scheme})`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.emulateMedia({ reducedMotion: "reduce", colorScheme: scheme });
      for (const route of ROUTES) {
        await page.goto(`${route}${route.includes("?") ? "&" : "?"}mock=1`);
        await expect(page.locator("main h1").first()).toBeVisible();
        const report = await page.evaluate(() => {
          const probe = document.createElement("div");
          probe.style.background = "var(--surface)";
          document.body.appendChild(probe);
          const surface = getComputedStyle(probe).backgroundColor;
          probe.remove();
          // Only what already blurred on desktop before session 37 may blur: the sidebar, the dialog overlay and the chart tooltips
          // (and the Workouts bulk bar, which none of these routes opens). The top bar's wrapper in particular must not.
          const blurred = [...document.querySelectorAll<HTMLElement>("body *")]
            .filter((el) => el.getClientRects().length && getComputedStyle(el).backdropFilter !== "none")
            .filter((el) => !el.matches("aside, .glass-overlay, [data-testid$='tooltip']"))
            .map((el) => `${el.tagName}.${String(el.className).slice(0, 60)}`);
          const cards = [...document.querySelectorAll<HTMLElement>(".glass-secondary[data-tone='default'], .glass-solid[data-tone]")]
            .filter((el) => el.getClientRects().length)
            .map((el) => getComputedStyle(el).backgroundColor);
          return {
            surface,
            blurred,
            cards,
            bodyImage: getComputedStyle(document.body).backgroundImage,
            bodyAttachment: getComputedStyle(document.body).backgroundAttachment,
            before: getComputedStyle(document.body, "::before").content,
          };
        });
        expect(report.blurred, `${route}: unexpected backdrop blur`).toEqual([]);
        for (const bg of report.cards) expect(bg, `${route}: a card is not on --surface`).toBe(report.surface);
        expect(report.bodyImage).toContain("radial-gradient");
        expect(report.bodyAttachment).toContain("fixed");
        expect(report.before).toBe("none");
      }
      await page.goto("/settings?mock=1");
      await expect(page.getByTestId("reduce-transparency")).toBeHidden();
    });
  }
}

test("an InfoTip opens beside its own button on desktop, inside the window", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/?mock=1");
  const button = page.getByRole("button", { name: /^About / }).first();
  await button.scrollIntoViewIfNeeded();
  await button.click();
  const t = (await page.getByRole("tooltip").boundingBox())!;
  const b = (await button.boundingBox())!;
  // Centred on the button (it once landed a sidebar's width to the right), and fully on screen.
  expect(Math.abs(t.x + t.width / 2 - (b.x + b.width / 2))).toBeLessThan(140);
  expect(t.y).toBeGreaterThanOrEqual(0);
  expect(t.y + t.height).toBeLessThanOrEqual(844);
});

