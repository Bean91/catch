import { defineConfig, devices } from "@playwright/test";

// Session 24: the one test in this repo with NOTHING mocked — a real browser against the real public build served by FastAPI
// (so the real Content-Security-Policy applies), connected as the unprivileged runtime role to a throwaway local Supabase stack
// (real GoTrue, real Postgres with RLS, real mail via mailpit). Skipped unless the stack is configured; see docs/public-setup.md §8.
//
//   (cd web && VITE_CATCH_DEPLOYMENT=public VITE_SUPABASE_URL=http://127.0.0.1:54321 VITE_SUPABASE_PUBLISHABLE_KEY=… npm run build)
//   supabase config: site_url + additional_redirect_urls = http://127.0.0.1:8799, enable_confirmations = true, mailpit on
//   CATCH_TEST_SUPABASE_URL=… CATCH_TEST_SUPABASE_PUBLISHABLE_KEY=… CATCH_TEST_SUPABASE_SECRET_KEY=… CATCH_TEST_RUNTIME_DB_URL=… npm run test:live
const env = process.env;
export default defineConfig({
  testDir: "./tests/live",
  timeout: 120_000,
  workers: 1,
  reporter: "list",
  webServer: env.CATCH_TEST_SUPABASE_URL
    ? {
        command: "cd .. && uv run uvicorn catch.main:app --port 8799",
        url: "http://127.0.0.1:8799/api/health",
        reuseExistingServer: false,
        timeout: 60_000,
        env: {
          ...(env as Record<string, string>),
          CATCH_DEPLOYMENT: "public",
          DATABASE_URL: env.CATCH_TEST_RUNTIME_DB_URL ?? "",
          SUPABASE_URL: env.CATCH_TEST_SUPABASE_URL,
          SUPABASE_PUBLISHABLE_KEY: env.CATCH_TEST_SUPABASE_PUBLISHABLE_KEY ?? "",
          SUPABASE_SECRET_KEY: env.CATCH_TEST_SUPABASE_SECRET_KEY ?? "",
          CATCH_TICK_SECRET: "live-tick-secret",
          CATCH_SESSION_CHECK_TTL: "0",
          CATCH_OLLAMA_ENABLED: "0",
          CATCH_BASE_URL: "http://127.0.0.1:8799",
        },
      }
    : undefined,
  use: { baseURL: "http://127.0.0.1:8799" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
