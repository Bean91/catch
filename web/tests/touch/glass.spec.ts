import { expect, test, type Locator, type Page } from "@playwright/test";
import { newTouchSession, touchHold } from "./cdpTouch";

// Session 37 (DESIGN.md "Mobile glass"): the phone/tablet layout's glass materials. Run in both themes, since every other suite runs
// light only. The desktop half of the contract (no glass at lg and up) is glass-desktop.spec.ts.

/** The alpha of a computed colour, whatever syntax the engine reports it in (rgba(), color(srgb … / a), oklab(… / a)). */
function alphaOf(color: string): number {
  const m = color.match(/\/\s*([\d.]+)\s*\)$/) ?? color.match(/^rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+)\)$/);
  if (color === "transparent") return 0;
  return m ? Number(m[1]) : 1;
}

async function style(loc: Locator, prop: string): Promise<string> {
  return loc.evaluate((el, p) => getComputedStyle(el).getPropertyValue(p), prop);
}

async function noHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
}

for (const scheme of ["dark", "light"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme });
    test.beforeEach(async ({ page }) => {
      await page.emulateMedia({ reducedMotion: "reduce" });
    });

    test("the tab bar floats as blurred glass, inset from the edges, with the lens under the active tab", async ({ page }) => {
      await page.goto("/?mock=1");
      const nav = page.getByRole("navigation", { name: "Primary" });
      expect(await style(nav, "backdrop-filter")).toContain("blur(");
      const box = (await nav.boundingBox())!;
      const vp = page.viewportSize()!;
      expect(box.x).toBeGreaterThanOrEqual(12);
      expect(box.x + box.width).toBeLessThanOrEqual(vp.width - 12);
      expect(box.y + box.height).toBeLessThanOrEqual(vp.height - 8);
      expect(alphaOf(await style(nav, "background-color"))).toBeLessThan(1);

      const lens = page.getByTestId("nav-lens");
      const underLens = async (name: string) => {
        const l = (await lens.boundingBox())!;
        const t = (await nav.getByRole("link", { name }).boundingBox())!;
        return Math.abs(l.x + l.width / 2 - (t.x + t.width / 2));
      };
      expect(await underLens("Today")).toBeLessThan(2);
      await nav.getByRole("link", { name: "Plan" }).tap();
      await expect(page).toHaveURL(/\/calendar/);
      await expect.poll(() => underLens("Plan")).toBeLessThan(2);
      await expect(nav.getByRole("link", { name: "Plan" })).toHaveAttribute("aria-current", "page");
    });

    test("cards are translucent, chart cards stay near-opaque, and a selected segment keeps its ring", async ({ page }) => {
      await page.goto("/trends?mock=1");
      const chartCard = page.locator(".glass-solid").filter({ has: page.locator('[data-chart-surface="true"]') }).first();
      await expect(chartCard).toBeVisible();
      expect(alphaOf(await style(chartCard, "background-color"))).toBeGreaterThanOrEqual(0.95);
      expect(await style(chartCard, "backdrop-filter")).toBe("none");

      await page.goto("/?mock=1");
      const card = page.locator(".glass-secondary[data-tone]").first();
      await expect(card).toBeVisible();
      expect(alphaOf(await style(card, "background-color"))).toBeLessThan(1);
      expect(await style(card, "backdrop-filter")).toBe("none");

      // Segmented's selected tab has `ring-1`: a material must keep Tailwind's ring in its box-shadow, not replace it.
      await page.goto("/calendar?mock=1");
      const selected = page.getByRole("tablist", { name: "Calendar view" }).getByRole("tab", { selected: true });
      expect(await style(selected, "box-shadow")).toMatch(/0px 0px 0px 1px/);
    });

    test("a sheet is near-opaque, unblurred, and still sits above the tab bar", async ({ page }) => {
      await page.goto("/calendar?mock=1");
      await page.getByRole("button", { name: /^Plan a session on/ }).first().tap();
      const sheet = page.getByRole("dialog");
      await expect(sheet).toBeVisible();
      expect(alphaOf(await style(sheet, "background-color"))).toBeGreaterThanOrEqual(0.95);
      expect(await style(sheet, "backdrop-filter")).toBe("none");
      const button = sheet.getByRole("button", { name: "Add to plan" });
      await button.scrollIntoViewIfNeeded();
      const hit = await button.evaluate((el) => {
        const r = el.getBoundingClientRect();
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return !!top && (el === top || el.contains(top));
      });
      expect(hit).toBe(true);
    });

    test("Reduce transparency makes every surface solid, and is remembered on this device", async ({ page }) => {
      await page.goto("/settings?mock=1");
      const toggle = page.getByTestId("reduce-transparency");
      await toggle.scrollIntoViewIfNeeded();
      await expect(toggle).toHaveAttribute("aria-checked", "false");
      await toggle.tap();
      await expect(toggle).toHaveAttribute("aria-checked", "true");
      await expect(page.locator("html")).toHaveAttribute("data-glass", "off");

      await page.reload();
      await expect(page.locator("html")).toHaveAttribute("data-glass", "off");
      const nav = page.getByRole("navigation", { name: "Primary" });
      expect(await style(nav, "backdrop-filter")).toBe("none");
      expect(alphaOf(await style(nav, "background-color"))).toBe(1);
      const card = page.locator(".glass-secondary").first();
      expect(alphaOf(await style(card, "background-color"))).toBe(1);
      expect(await page.evaluate(() => getComputedStyle(document.body, "::before").display)).toBe("none");

      await page.getByTestId("reduce-transparency").tap();
      await expect(page.locator("html")).not.toHaveAttribute("data-glass", "off");
      expect(await style(nav, "backdrop-filter")).toContain("blur(");
    });
  });
}

test("at 320px the floating bar fits its labels and nothing scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/?mock=1");
  const nav = page.getByRole("navigation", { name: "Primary" });
  const clipped = await nav.locator("a span, button span").evaluateAll((els) => els.filter((el) => el.scrollWidth > el.clientWidth).map((el) => el.textContent));
  expect(clipped).toEqual([]);
  await noHorizontalOverflow(page);
});

test("a chart's press-and-hold tooltip is near-opaque and unblurred (it moves every frame)", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "press-and-hold needs CDP touch");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/trends?mock=1&range=12w");
  await expect(page.getByRole("img", { name: /Trend over time/ })).toBeVisible();
  // Same readiness wait as charts.spec: the navigator's floor settles once the full-history query resolves.
  await expect
    .poll(async () => Number(await page.locator('[role="slider"]').getAttribute("aria-valuemin")), { timeout: 3000 })
    .toBeLessThan(Date.now() - 100 * 86_400_000);
  // A point on the chart that nothing (the sticky top bar, the floating tab bar) covers.
  const at = await page.evaluate(() => {
    const surface = document.querySelector('[data-chart-surface="true"]') as HTMLElement;
    const r = surface.getBoundingClientRect();
    for (const f of [0.5, 0.35, 0.65, 0.2, 0.8]) {
      const point = { x: r.left + r.width / 2, y: r.top + r.height * f };
      const el = document.elementFromPoint(point.x, point.y);
      if (el && surface.contains(el)) return point;
    }
    return null;
  });
  expect(at).not.toBeNull();
  const cdp = await newTouchSession(page);
  const hold = touchHold(cdp, at!, 900);
  const tip = page.getByTestId("chart-tooltip");
  await expect(tip).toBeVisible({ timeout: 2500 });
  expect(await style(tip, "backdrop-filter")).toBe("none");
  expect(alphaOf(await style(tip, "background-color"))).toBeGreaterThanOrEqual(0.95);
  await hold;
});

test("an InfoTip opens next to its button, above the tab bar near the bottom of the screen", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/workouts/1?mock=1");
  const button = page.getByRole("button", { name: /^About / }).first();
  await button.scrollIntoViewIfNeeded();
  // Put the button just above the tab bar, where opening downwards would run under it.
  await page.evaluate(() => {
    const b = document.querySelector('button[aria-label^="About "]')!.getBoundingClientRect();
    window.scrollBy(0, b.bottom - (window.innerHeight - 90));
  });
  // A dispatched click, not tap(): Playwright's WebKit tap scrolls the page first, which would move the button off this spot.
  await button.dispatchEvent("click");
  const tip = page.getByRole("tooltip");
  await expect(tip).toBeVisible();
  const t = (await tip.boundingBox())!;
  const b = (await button.boundingBox())!;
  const nav = (await page.getByRole("navigation", { name: "Primary" }).boundingBox())!;
  expect(t.y).toBeGreaterThanOrEqual(0);
  expect(t.y + t.height).toBeLessThanOrEqual(nav.y);
  expect(Math.abs(t.y + t.height - (b.y - 8))).toBeLessThan(2);
  expect(t.x).toBeGreaterThanOrEqual(0);
  expect(t.x + t.width).toBeLessThanOrEqual(page.viewportSize()!.width);
});

test("the system's increased-contrast preference turns glass off the same way", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce", contrast: "more" });
  await page.goto("/?mock=1");
  const nav = page.getByRole("navigation", { name: "Primary" });
  expect(await style(nav, "backdrop-filter")).toBe("none");
  expect(alphaOf(await style(nav, "background-color"))).toBe(1);
  expect(alphaOf(await style(page.locator(".glass-secondary").first(), "background-color"))).toBe(1);
});
