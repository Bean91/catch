import { execFileSync, execSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

// Separate from playwright.config.ts (touch gestures, mock-only dev server) and
// playwright.update.config.ts (two static builds, no backend): this suite needs a REAL
// backend — the offline queue's sync endpoint actually has to upsert sets, run the matching
// engine, and merge with a Garmin activity, none of which a static server or ?mock=1 can
// exercise. Builds the real frontend into catch/api/static (the normal `npm run build`
// location — not a secret, unlike the DB/session key below) and runs the real
// `uv run uvicorn catch.main:app` against a disposable scratch DB and freshly generated
// secrets, matching session 4/5/6's "disposable instance, never the real .env/data/catch.db"
// precedent, just automated via Playwright's `webServer` instead of done by hand.
//
// TEST_PASSWORD (tests/gym-offline/*.spec.ts hardcode the same literal string to log in) must
// stay in sync with this file by hand — not imported from here, so a worker process importing
// this module doesn't redundantly re-run the build/secret-generation below.
const PORT = 8731;
const webDir = path.resolve(import.meta.dirname);
const repoRoot = path.resolve(webDir, "..");

const scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "catch-gym-offline-"));
process.env.CATCH_GYM_TEST_SCRATCH_DIR = scratchDir;
const dbPath = path.join(scratchDir, "catch.db");
const TEST_PASSWORD = "correct-horse-battery-staple";

function pythonSecrets(): { passwordHash: string; fernetKey: string } {
  const script = [
    "from argon2 import PasswordHasher",
    "from cryptography.fernet import Fernet",
    `print(PasswordHasher().hash(${JSON.stringify(TEST_PASSWORD)}))`,
    "print(Fernet.generate_key().decode())",
  ].join("\n");
  const out = execFileSync("uv", ["run", "python3", "-c", script], { cwd: repoRoot, encoding: "utf-8" });
  const [passwordHash, fernetKey] = out.trim().split("\n");
  return { passwordHash, fernetKey };
}

const { passwordHash, fernetKey } = pythonSecrets();

// Built once, synchronously, before webServer starts — Playwright's config loading is
// synchronous, and webServer needs a real catch/api/static the moment uvicorn boots.
execSync("npx tsc -b && npx vite build", { cwd: webDir, stdio: "inherit" });

export default defineConfig({
  testDir: "./tests/gym-offline",
  testMatch: /.*\.spec\.ts/,
  timeout: 60_000,
  workers: 1,
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${PORT}` },
  webServer: {
    command: `uv run uvicorn catch.main:app --host 127.0.0.1 --port ${PORT}`,
    cwd: repoRoot,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 20_000,
    env: {
      CATCH_ENV: "test",
      CATCH_PORT: String(PORT),
      CATCH_DB_PATH: dbPath,
      CATCH_BASE_URL: `http://127.0.0.1:${PORT}`,
      CATCH_PASSWORD_HASH: passwordHash,
      CATCH_SESSION_SECRET: randomBytes(32).toString("hex"),
      CATCH_FERNET_KEY: fernetKey,
      // A long interval plus APScheduler's own first-fire-after-one-interval default means no
      // real sync job fires during this short test run — no live Garmin/Withings/Concept2 call
      // risk even with every source's own key left unset (CLAUDE.md's "no live network calls").
      SYNC_INTERVAL_HOURS: "24",
    },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  globalTeardown: "./tests/gym-offline/globalTeardown.mjs",
});
