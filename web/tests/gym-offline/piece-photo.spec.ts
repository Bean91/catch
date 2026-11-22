import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Session 33, Part D: a piece from a PM5 photo, front end to a REAL backend (this suite's disposable uvicorn + scratch SQLite).
// Only the AI provider is faked (no key exists here, and nothing may call a real provider): GET /api/ai/providers says photos are
// available and the photo-estimate answers with a screen that shows totals only — the case that could never be saved before.
// Everything after that is real: the file chosen, the client-side resize, the multipart create-with-photo request, the server's
// validation and single transaction, the photo served back, then replacing and removing it.

const TEST_PASSWORD = "correct-horse-battery-staple";
const repoRoot = path.resolve(import.meta.dirname, "..", "..", "..");
// A real 8×8 PNG, so the browser's own image decoding and canvas resize run as they would for a phone photo.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR4nGOoiDqBFTEMLQkA+RFmgRtoVlEAAAAASUVORK5CYII=",
  "base64",
);

test.use({ serviceWorkers: "block" }); // so page.route sees the two faked AI requests

function seedRow(externalId: string): number {
  const script = [
    "from datetime import datetime, timedelta, timezone",
    "from sqlmodel import Session",
    "from catch.core import db",
    "from catch.sync.upsert import upsert_activity",
    "with Session(db.engine) as s:",
    `    a = upsert_activity(s, 'garmin', ${JSON.stringify(externalId)}, type='indoor_rowing', start=datetime.now(timezone.utc) - timedelta(hours=3), duration=3600.0, distance=12000.0, avg_hr=140.0)`,
    "    print(a.canonical_id)",
  ].join("\n");
  const out = execFileSync("uv", ["run", "python3", "-c", script], {
    cwd: repoRoot,
    encoding: "utf-8",
    env: { ...process.env, CATCH_DEPLOYMENT: "personal", CATCH_DB_PATH: path.join(process.env.CATCH_GYM_TEST_SCRATCH_DIR!, "catch.db") },
  });
  return Number(out.trim().split("\n").pop());
}

async function login(page: Page) {
  const resp = await page.request.post("/api/login", { data: { password: TEST_PASSWORD } });
  expect(resp.ok()).toBeTruthy();
}

async function fakeVision(page: Page) {
  await page.route("**/api/ai/providers", (route) =>
    route.fulfill({ json: { active: "anthropic", providers: [], vision: { available: true, provider: "anthropic", reason: null } } }),
  );
  await page.route("**/pieces/photo-estimate", (route) =>
    route.fulfill({
      json: {
        modality: "rowing_erg",
        detected_piece_type: "5000m",
        splits: [],
        distance_m: 5000,
        duration_s: 1185.0,
        avg_split_s: 118.5,
        avg_rate: 26,
        avg_watts: null,
        drag_factor: 120,
        validation: { ok: true, issues: [] },
        notes: "Only the totals were visible on this screen.",
        cost_usd: 0.01,
      },
    }),
  );
}

test("a totals-only PM5 photo saves a piece with its photo, which can be viewed, replaced and removed", async ({ page }) => {
  const canonicalId = seedRow("photo-e2e-1");
  await login(page);
  await fakeVision(page);
  await page.goto(`/workouts/${canonicalId}`);

  await page.getByRole("button", { name: "Add piece" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator('input[type="file"]').setInputFiles({ name: "pm5.png", mimeType: "image/png", buffer: PNG });

  await expect(dialog.getByTestId("piece-photo-preview")).toBeVisible();
  await expect(dialog.getByRole("combobox")).toHaveValue("5000m"); // the type the screen's totals imply, for the athlete to confirm
  await expect(dialog.getByLabel("Total distance (m)")).toHaveValue("5000");
  const created = page.waitForResponse((r) => r.url().includes("/pieces/with-photo") && r.request().method() === "POST");
  await dialog.getByRole("button", { name: "Save piece" }).click();
  const resp = await created;
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.piece.has_photo).toBe(true);
  expect(body.piece.avg_split_s).toBeCloseTo(118.5, 1);
  const pieceId: number = body.piece.id;

  const card = page.getByRole("heading", { name: "Pieces" }).locator("xpath=ancestor::div[contains(@class,'rounded-lg')][1]");
  await expect(card.getByText("5000m", { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "View photo" }).click();
  const img = card.getByRole("img", { name: "PM5 screen" });
  await expect(img).toBeVisible();
  await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0); // real bytes, served back by the backend

  const replaced = page.waitForResponse((r) => r.url().endsWith(`/api/pieces/${pieceId}/photo`) && r.request().method() === "POST");
  await page.getByTestId(`piece-photo-input-${pieceId}`).setInputFiles({ name: "again.png", mimeType: "image/png", buffer: PNG });
  expect((await replaced).status()).toBe(200);

  await card.getByRole("button", { name: "Remove photo" }).click();
  await expect(card.getByRole("button", { name: "Add photo" })).toBeVisible();
  const after = await page.request.get(`/api/pieces/${pieceId}/photo`);
  expect(after.status()).toBe(404);
});

test("when saving fails, the athlete is told nothing was saved and no piece exists", async ({ page }) => {
  const canonicalId = seedRow("photo-e2e-2");
  await login(page);
  await fakeVision(page);
  await page.route("**/pieces/with-photo", (route) => route.fulfill({ status: 413, json: { detail: "That photo is too large (max 5 MB)." } }));
  await page.goto(`/workouts/${canonicalId}`);

  await page.getByRole("button", { name: "Add piece" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator('input[type="file"]').setInputFiles({ name: "pm5.png", mimeType: "image/png", buffer: PNG });
  await dialog.getByRole("button", { name: "Save piece" }).click();
  await expect(dialog.getByText("That photo is too large (max 5 MB). Nothing was saved.")).toBeVisible();
  const pieces = await page.request.get(`/api/activities/${canonicalId}/pieces`).then((r) => r.json());
  expect(pieces.pieces).toHaveLength(0);
});
