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
tokens as CSS vars), Radix primitives, Framer Motion, TanStack Query, React Router — built to
`catch/api/static` (gitignored), served by FastAPI. No Docker, no Postgres, no Redis, no Node
at runtime (Node is a build-time-only dependency; the Pi never runs `npm`).

## Layout

```
catch/
  api/          FastAPI routers (routes_coach.py: shared tool endpoints + coach settings/
                conversations/memory/device tokens; sse.py: cancels a streaming response's
                generator on client disconnect — see PLAN.md's session 6 Findings for why
                that needs its own polling helper, not just a per-event check)
  core/         SQLModel models, config, db, security
  sync/         garmin_client, withings_client, scheduler, upsert helpers
  analytics/    recovery/strain/load/zones/predict/technique — pure functions, no I/O
  coach/        tools.py (the ONE shared tool registry — in-app coach, MCP server, and
                GET/POST /api/coach/tools all call catch.coach.tools.call_tool, never
                duplicated), chat.py (provider-neutral orchestration loop: tool-calling,
                SSE events, cost/cap accounting), memory.py (events/goals/athlete_facts
                CRUD + recall + the compact system-prompt memory block), settings.py
                (coach prefs + Fernet-encrypted API key — a separate table from `settings`,
                see the Gotchas section), cost.py (usage -> $ from user-entered prices),
                system_prompt.md (editable coach persona), providers/ (anthropic_provider.py,
                ollama_provider.py — both yield the same normalized event stream)
  mcp_server/   server.py (MCPServer + all 16 tools + 2 prompts, built once, shared by both
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
                charts/ (TrendLineChart, WeeklyVolumeBars, ErgChart — hand-rolled SVG, no
                chart library; lazy-loaded with the page that uses them), shell/ (AppShell,
                Sidebar, BottomNav), coach/ (Timeline, ToolCallChip, SuggestedPrompts,
                CoachSettingsCard)
    lib/        api.ts (fetch + mock switch; streamMessage() parses the coach's SSE body by
                hand since EventSource can't POST), types.ts (hand-kept in sync with the
                API — no codegen), mock.ts (?mock=1/calibrating/empty/error/loading
                fixtures, incl. a scripted streamMockMessage() turn), format.ts, auth.tsx,
                theme.tsx, zoneColors.ts/hrZone.ts (zone color ramp + a small TS port of
                catch/analytics/zones.py's zone_for_hr for client-side chart coloring),
                dateRanges.ts (Trends' 4w/12w/season/all -> from/to), timeline.ts (merges a
                conversation's tool_call/tool_result block pairs — stored on two separate
                message rows — into one display entry), toolLabels.ts (mirrors
                catch/coach/chat.py's chip-label templates for persisted history)
    pages/      Today.tsx (eager); Workouts, WorkoutDetail, Trends, Body, Coach, Settings,
                Memory (React.lazy, one chunk per route — keeps the initial bundle under
                budget)
    styles/     tokens.css — design tokens as CSS vars, see /DESIGN.md
  public/       manifest.webmanifest, icons/ (generated, see /DESIGN.md); sw.js is NOT
                here — vite.config.ts's serviceWorkerPlugin writes it at build time with
                the real hashed asset list, so it can't be a static passthrough file
tests/          fixtures/ has recorded JSON; no live network calls in the suite; coach/ has
                the tool-layer, chat-loop, and provider tests (Anthropic client mocked,
                Ollama mocked via httpx.MockTransport)
docs/           garmin-endpoints.md, withings-endpoints.md, garmin-openapi.json,
                analytics.md, mcp.md (Claude Desktop config, device tokens, Inspector)
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
  from `.env`; append `?mock=1` (or `?mock=calibrating|empty|error|loading`) to run the UI
  against fixtures with no backend at all
- `cd web && npm run build` — builds to `catch/api/static`, which FastAPI serves at `/`
  (gitignored; not committed — the Pi has no Node, so the build must run elsewhere and the
  `catch/api/static` output deployed alongside the backend)

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
