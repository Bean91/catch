import { defineConfig, devices } from "@playwright/test";

// Regression coverage for the real-iOS touch bug (see DESIGN.md's "Chart touch-action" note
// and useChartInteraction.ts's file-level comment): Chromium's CDP touch emulation was all
// session 8 tested against, and it didn't catch the real WebKit bug. Two engines, deliberately:
//
// - `mobile-gestures` (Chromium + an iPhone device profile): Playwright's own WebKit bindings
//   only expose `touchscreen.tap()` — no touch *move*, no multi-touch — so pan/pinch/hold
//   gestures are driven here via CDP's `Input.dispatchTouchEvent` (Chromium-only), which still
//   exercises hasTouch/isMobile + this app's real Pointer Event handlers.
// - `mobile-webkit` (real WebKit engine): catches engine-specific CSS/behavior gaps a tap
//   alone can verify — computed `touch-action`, the iOS touch-callout suppression, basic tap
//   navigation — the things Chromium's engine can't be trusted to reproduce either way.
export default defineConfig({
  testDir: "./tests/touch",
  timeout: 30_000,
  fullyParallel: true,
  reporter: "list",
  webServer: {
    // CI runs against the real production build (`vite preview`, no dev-server transform/HMR
    // overhead and no live source dependency) — the same artifact `check:bundle-size` just
    // measured and that deploy.sh ships; a local run keeps the dev server for fast iteration.
    command: process.env.CI ? "npm run preview:test" : "npm run dev -- --port 5190 --strictPort",
    port: 5190,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  use: {
    baseURL: "http://localhost:5190",
  },
  projects: [
    {
      name: "mobile-gestures",
      use: { ...devices["iPhone 13"], browserName: "chromium" },
      testIgnore: /(mouse|route-map-desktop|library-desktop|ai-providers-desktop)\.spec\.ts/,
    },
    {
      name: "mobile-webkit",
      use: { ...devices["iPhone 13"] },
      testIgnore: /(mouse|route-map-desktop|library-desktop|ai-providers-desktop)\.spec\.ts/,
    },
    // The task's "mouse ... profile" — plain desktop Chromium, no touch emulation, so mouse
    // wheel/drag/click paths (DESIGN.md's ctrl/cmd+wheel zoom, drag-to-pan) run through
    // `useChartInteraction.ts`'s pointer-event handlers the way a laptop user actually would.
    // Scoped to mouse.spec.ts only — the other spec files assume CDP touch dispatch/a
    // 390px iPhone viewport, neither of which this project has.
    {
      name: "desktop-mouse",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /(mouse|route-map-desktop|library-desktop|ai-providers-desktop)\.spec\.ts/,
    },
  ],
});
