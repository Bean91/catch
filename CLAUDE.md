# Catch

Self-hosted, single-user rowing training app. Garmin + Withings + Concept2 data, Whoop-style
recovery/strain, an AI coach (bring-your-own Anthropic key or a local Ollama model) with a
shared MCP server for Claude Desktop. Runs 24/7 on a Raspberry Pi 3 (1GB RAM, ARM) alongside
PiAware.

## Stack

Python 3.12 via `uv`, FastAPI + uvicorn, SQLModel on SQLite (WAL mode), httpx, APScheduler
3.x, pytest, `cryptography` (Fernet), `argon2-cffi` (verify the password hash already in
`.env`), `anthropic` (official SDK, lazy-imported), `mcp` (official Python SDK, lazy-imported
for the optional HTTP transport). Frontend: React + Vite + TS, Tailwind v4 (CSS-first config,
tokens as CSS vars), Radix primitives, Framer Motion, TanStack Query, React Router,
`barcode-detector` (session 13: a ponyfill over a self-hosted ZXing-wasm binary — Vite's
`?url` import serves it from `/assets` rather than the package's default jsDelivr-CDN fetch —
used only as a fallback when `window.BarcodeDetector` is absent, e.g. iOS Safari) — built to
`catch/api/static` (gitignored), served by FastAPI. No Docker, no Postgres, no Redis, no Node
at runtime (Node is a build-time-only dependency; the Pi never runs `npm`).

## Layout

```
catch/
  api/          FastAPI routers (routes_coach.py: shared tool endpoints + coach settings/
                conversations/memory/device tokens; sse.py: cancels a streaming response's
                generator on client disconnect — see PLAN.md's session 6 Findings for why
                that needs its own polling helper, not just a per-event check; session 13:
                routes_nutrition.py — foods/barcode/logs/my-foods/saved-meals/targets/
                photo-estimate)
  core/         SQLModel models, config, db, security
  sync/         garmin_client, withings_client, concept2_client, scheduler, upsert helpers;
                session 8/12 (cross-source matching + Peloton + body comp + per-sample
                zones/strain — see PLAN.md): matching.py (the DB-facing half of the matching
                engine — ensure_canonicals/find_candidate_pairs/apply_auto_merges/manual
                merge-split-not_duplicate, run after every sync), canonical.py
                (resolve_canonical — field-priority merge of a canonical's member Activity
                rows into its displayed fields + auto-title, plus its zones/strain via
                zones_samples.py), fit_parse.py (streams a FIT file's record/lap messages
                with `fitdecode`, Peloton detection via file_id.manufacturer), samples.py
                (builds the 1Hz sample arrays FIT parsing or Concept2 strokes produce and
                writes ActivitySamples), body_comp.py (one resolved daily body-comp reading
                across however many scales reported one), rowing_predict.py (shared
                "recent best Concept2 pieces" gathering for GET /api/predict/2k and the erg
                power-zone threshold); session 13: nutrition.py (the DB-facing nutrition
                layer — food search/barcode-lookup-or-fetch/logging/my-foods/saved-meals/
                targets/week-summary, shared by routes_nutrition.py and the coach tools),
                openfoodfacts_client.py (barcode-only OFF v2 lookup, rate-limited + negative-
                cached), usda_client.py (USDA FDC branded-food search/barcode/detail, used
                for free-text search since OFF has none)
  analytics/    recovery/strain/load/zones/predict/technique — pure functions, no I/O;
                session 8/12: matching.py (sport_family/is_indoor/match_pair — the pure
                scoring half of cross-source matching), cycling_load.py (TSS-style power
                load + FTP estimate), samples_codec.py (pack/unpack the compact per-sample
                blobs), zones_samples.py (per-sample time-in-zone/Banister-TRIMP/session-
                label/auto-trim-detection — the real zones/strain fix for a session whose
                average HR undersells a short hard block inside a long easy one); session 13:
                nutrition.py (pure target/macro-scaling/under-fuelling math, no I/O)
  coach/        tools.py (the ONE shared tool registry — in-app coach, MCP server, and
                GET/POST /api/coach/tools all call catch.coach.tools.call_tool, never
                duplicated), chat.py (provider-neutral orchestration loop: tool-calling,
                SSE events, cost/cap accounting), memory.py (events/goals/athlete_facts
                CRUD + recall + the compact system-prompt memory block), settings.py
                (coach prefs + Fernet-encrypted API key — a separate table from `settings`,
                see the Gotchas section), cost.py (usage -> $ from user-entered prices,
                incl. session 13's AiUsageEvent rows so photo-estimate spend counts against
                the same daily cap as chat), system_prompt.md (editable coach persona),
                providers/ (anthropic_provider.py, ollama_provider.py — both yield the same
                normalized event stream), nutrition_vision.py (session 13: one-shot Anthropic
                vision call for an itemised meal-photo macro estimate; lazy-imported, hidden
                when no Anthropic key is configured, photos never stored after the estimate)
  mcp_server/   server.py (MCPServer + all 21 tools + 2 prompts, built once, shared by both
                transports), backend.py (RestBackend for stdio -> HTTP with a device
                token; InProcessBackend for the /mcp mount, which dispatches straight into
                catch.coach.tools to avoid a same-process HTTP deadlock), __main__.py
                (catch-mcp stdio entry point), http_app.py (the /mcp/ mount + its bearer
                auth middleware)
  cli.py        argparse entry point (`uv run catch ...`, now incl. `token create`/`list`)
  main.py       FastAPI app factory
web/
  src/
    components/ ui/ (Card, Badge, Skeleton, …), today/ (RecoveryRing, StrainGauge, …),
                workouts/ (WorkoutRow, IntervalTable, ZoneTable, NotesBox, PbTable),
                charts/ (TrendLineChart, WeeklyVolumeBars, ErgChart, HrChart — session 8/12's
                per-sample HR graph on workout detail: zone-shaded bands, dashed max/avg HR,
                lap markers, the auto-trimmed tail greyed out (not absent — GET
                /api/activities/{id}/samples returns the full recording by default), a
                power/cadence overlay toggle — ChartNavigator — hand-rolled SVG, no chart
                library; lazy-loaded with the page that uses them; no
                on-chart zoom buttons — they covered data at 390px, see DESIGN.md's "On-chart
                zoom buttons removed" note; pan/pinch/press-hold run through the shared
                lib/useChartInteraction.ts hook against `touch-action: none` HTML wrapper divs,
                never the `<svg>` itself — WebKit's touch-action support on SVG root elements
                has real gaps, see DESIGN.md's "Chart touch-action" note), shell/ (AppShell,
                Sidebar, BottomNav, UpdateToast — the "New version — tap to reload" banner),
                coach/ (Timeline, ToolCallChip, SuggestedPrompts, CoachSettingsCard),
                nutrition/ (session 13: AddFoodDialog — search/My-Foods/saved-meals quick
                picks/barcode-scan/manual-entry, one flow; BarcodeScanner — lazy-loaded,
                native BarcodeDetector or the self-hosted ZXing-wasm fallback via
                lib/barcodeScan.ts, stops every camera track on close; PhotoEstimateDialog —
                lazy-loaded, client-side ~1500px JPEG resize before upload, editable itemised
                estimate; MealSection, MacroBar, WeekView, NutritionTargetsCard)
    lib/        api.ts (fetch + mock switch; streamMessage() parses the coach's SSE body by
                hand since EventSource can't POST), types.ts (hand-kept in sync with the
                API — no codegen), mock.ts (?mock=1/calibrating/empty/error/loading/offline
                fixtures, incl. a scripted streamMockMessage() turn), format.ts, auth.tsx,
                theme.tsx, zoneColors.ts/hrZone.ts (zone color ramp + a small TS port of
                catch/analytics/zones.py's zone_for_hr for client-side chart coloring),
                dateRanges.ts (Trends' 4w/12w/season/all -> from/to), chartRange.ts (preset <->
                URL querystring helpers), useChartInteraction.ts (the shared pan/pinch/press-hold
                gesture engine every chart uses), useOnlineStatus.ts (the Today offline banner's
                only signal — an actual /api/health probe, never navigator.onLine or a cached-
                response heuristic; see session 10's PLAN.md notes), useServiceWorkerUpdate.ts
                (registers sw.js for its caching behavior, but drives the update toast off a
                separate version.json poll — deliberately not off the service worker's own
                install/waiting/controllerchange timing, which a session 10 bug report showed
                isn't reliable enough on a real iOS PWA to be the only signal), timeline.ts
                (merges a conversation's tool_call/tool_result block pairs — stored on two
                separate message rows — into one display entry), toolLabels.ts (mirrors
                catch/coach/chat.py's chip-label templates for persisted history),
                barcodeScan.ts (session 13: createBarcodeDetector() — native
                window.BarcodeDetector when present, else the self-hosted ZXing-wasm ponyfill;
                one detect() shape either way)
    pages/      Today.tsx (eager); Workouts (session 8/12: a Select mode for bulk retype/
                tag/exclude-from-totals, links to Duplicates), Duplicates (the flagged-
                possible-duplicate-pairs review screen, merge/not-duplicate actions),
                WorkoutDetail (inline title/sport/tags/RPE/exclude editing with
                revert-to-source, a per-metric field-source panel, the HrChart), Trends,
                Body (session 8/12: per-day resolved weight/fat%/muscle with its source,
                a manual-weight-entry form), Nutrition (session 13: day/week toggle, macro
                bars vs. targets, per-meal quick-add/copy-yesterday/edit/delete, barcode scan
                and photo-estimate entry points), Coach, Settings, Memory (React.lazy, one
                chunk per route — keeps the initial bundle under budget)
    styles/     tokens.css — design tokens as CSS vars, see /DESIGN.md
  public/       manifest.webmanifest, icons/ (generated, see /DESIGN.md); sw.js is NOT
                here — vite.config.ts's serviceWorkerPlugin writes it at build time with
                the real hashed asset list, so it can't be a static passthrough file
tests/          fixtures/ has recorded JSON; no live network calls in the suite; coach/ has
                the tool-layer, chat-loop, and provider tests (Anthropic client mocked,
                Ollama mocked via httpx.MockTransport). `web/` has its own test trees:
                `web/src/**/*.test.ts` (Vitest, pure-function unit tests, e.g. chartRange.ts) and
                `web/tests/touch/` (Playwright, real touch-device gesture regression tests —
                `playwright.config.ts` runs a Chromium+iPhone-profile project driven via CDP
                multi-touch, since Playwright's own WebKit bindings only support a single tap
                with no move/multi-touch; a real-WebKit project covers what a tap alone can
                verify, e.g. computed `touch-action`) and `web/tests/update/` (Playwright,
                `playwright.update.config.ts` — builds two real production bundles with distinct
                `CATCH_BUILD_ID`s, serves one then the other from an in-process swappable static
                server (server.mjs, not catch.main — booting the real app starts APScheduler
                against the real .env) to confirm a client on build A actually detects and
                reloads to build B, plus the offline-banner scenarios)
docs/           garmin-endpoints.md, withings-endpoints.md, garmin-openapi.json,
                analytics.md, mcp.md (Claude Desktop config, device tokens, Inspector),
                peloton.md (session 8/12: Peloton-push detection mechanism + live findings —
                no Peloton-pushed activity exists in this account yet to confirm it against),
                nutrition-endpoints.md (session 13: Open Food Facts v2 + USDA FoodData
                Central API facts — rate limits, field shapes, OFF's legacy free-text search
                endpoint and why it's the lowest-priority search source)
DESIGN.md       palette/type/motion decisions for the web frontend
```

## Commands

- `uv sync` — install deps
- `uv run catch sync --source garmin --days 30` — sync one source
- `uv run catch backfill` — backfill `BACKFILL_DAYS` from `.env`
- `uv run catch token create --name <device>` — mint a device bearer token for the MCP
  server (prints it once; see `docs/mcp.md`)
- `uv run uvicorn catch.main:app --reload --port $CATCH_PORT` — dev server (port comes from `.env`)
- `uv run pytest` — tests (fixtures only, never hits live APIs)
- `uv run catch-mcp` — MCP stdio server for Claude Desktop (needs `CATCH_BASE_URL` +
  `CATCH_MCP_TOKEN` env vars; see `docs/mcp.md`)
- `cd web && npm install` — install frontend deps
- `cd web && npm run dev` — Vite dev server, proxies `/api` and `/auth` to the FastAPI port
  from `.env`; append `?mock=1` (or `?mock=calibrating|empty|error|loading|offline`) to run the
  UI against fixtures with no backend at all
- `cd web && npm run build` — builds to `catch/api/static`, which FastAPI serves at `/`
  (gitignored; not committed — the Pi has no Node, so the build must run elsewhere and the
  `catch/api/static` output deployed alongside the backend)
- `cd web && npm run test` — Vitest (pure-function unit tests only)
- `cd web && npm run test:touch` — Playwright real-touch-device gesture regression tests
  (installs its own Chromium/WebKit via `npx playwright install` the first time; starts its own
  dev server on port 5190, no backend needed since it runs against `?mock=1`)
- `cd web && npm run test:update` — Playwright service-worker update + offline-banner tests;
  builds two real production bundles itself (no `.env`/backend needed) and serves them from its
  own swappable static server on port 5192
- `./deploy.sh` — build the frontend + rsync the backend to the Pi + restart + health-check
  (needs `deploy/pi-bootstrap.sh` to have been run on the Pi at least once; see that file)

## Conventions

- Upserts are idempotent, keyed on `(source, external_id)` (or `date` for the single-source
  `daily_wellness` aggregate). Never duplicate a row on re-sync.
- Garmin: **only** endpoints verified in `docs/garmin-openapi.json` / `garmin-endpoints.md`.
  Never invent an endpoint or response field. Task fields Garmin doesn't expose stay `NULL`
  and are noted in `docs/garmin-endpoints.md`, not silently dropped.
- Withings: current docs require HMAC-signed `requesttoken` calls — see
  `docs/withings-endpoints.md` before touching `sync/withings_client.py`.
- Stream downloads (FIT zips) and page through history — never load years of data into RAM.
  This box has 1GB total, shared with PiAware.
- No comments explaining *what* code does. Only *why*, for non-obvious Garmin/Withings field
  mappings or Pi-memory tradeoffs.

## Pi 3 limits

- 1GB RAM shared with PiAware — keep per-request memory bounded, stream large responses.
- ARM — avoid deps that need compiling heavy C extensions; prefer pure-Python or wheels with
  ARM builds already on PyPI.
- Single uvicorn worker — more than one means duplicate APScheduler jobs.

## Secrets

Everything sensitive lives in `.env` (gitignored). `.env.example` documents every key with
no real values. Never commit `.env`, the SQLite DB, or downloaded FIT files. Never print env
values to logs or chat — key *names* only when debugging.
