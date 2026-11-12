import { defineConfig, devices } from "@playwright/test";

// Session 24: the PUBLIC build's sign-in flow (Supabase Auth in the browser, bearer token to Catch's API). The dev
// server runs with VITE_CATCH_DEPLOYMENT=public; every Supabase and /api call is intercepted by the spec, so no
// backend or Supabase project is needed. (The real GoTrue + FastAPI path is covered by tests/pg in the Python suite.)
export default defineConfig({
  testDir: "./tests/public",
  timeout: 30_000,
  fullyParallel: true,
  reporter: "list",
  webServer: {
    command:
      "VITE_CATCH_DEPLOYMENT=public VITE_SUPABASE_URL=http://supabase.test VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_test npm run dev -- --port 5194 --strictPort",
    port: 5194,
    reuseExistingServer: false,
    timeout: 30_000,
  },
  use: { baseURL: "http://localhost:5194" },
  projects: [
    { name: "mobile", use: { ...devices["iPhone 13"], browserName: "chromium" } },
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
  ],
});
