import type { Page } from "@playwright/test";

// A valid 1x1 PNG. Map tiles are stubbed so these tests never touch the real OSM servers.
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

export async function stubTiles(page: Page): Promise<{ count: () => number }> {
  let n = 0;
  await page.route("**/tile.openstreetmap.org/**", (route) => {
    n++;
    return route.fulfill({ status: 200, contentType: "image/png", body: PNG_1X1 });
  });
  return { count: () => n };
}

export async function noHorizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}
