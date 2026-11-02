import { defineConfig, devices } from "@playwright/test";

// Separate from playwright.config.ts (touch gestures, dev server, mobile profiles): this suite
// serves two real production builds from a swappable in-process static server (tests/update/
// server.mjs) to simulate a deploy landing under an already-open tab — the dev server never
// emits sw.js/version.json at all (serviceWorkerPlugin only runs on `vite build`'s writeBundle),
// so it can't exercise this. One worker: tests share the server's mutable "current build" state
// and must run in a fixed order within the file.
export default defineConfig({
  testDir: "./tests/update",
  testMatch: /.*\.spec\.ts/,
  timeout: 30_000,
  workers: 1,
  reporter: "list",
  globalSetup: "./tests/update/globalSetup.mjs",
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
