# Catch

Self-hosted, single-user rowing training app. Garmin + Withings + Concept2 data, Whoop-style
recovery/strain, AI coach later. Runs 24/7 on a Raspberry Pi 3 (1GB RAM, ARM) alongside PiAware.

## Stack

Python 3.12 via `uv`, FastAPI + uvicorn, SQLModel on SQLite (WAL mode), httpx, APScheduler
3.x, pytest, `cryptography` (Fernet), `argon2-cffi` (verify the password hash already in
`.env`). Frontend: React + Vite + TS, Tailwind v4 (CSS-first config, tokens as CSS vars),
Radix primitives, Framer Motion, TanStack Query, React Router — built to `catch/api/static`
(gitignored), served by FastAPI. No Docker, no Postgres, no Redis, no Node at runtime (Node
is a build-time-only dependency; the Pi never runs `npm`).

## Layout

```
catch/
  api/          FastAPI routers
  core/         SQLModel models, config, db, security
  sync/         garmin_client, withings_client, scheduler, upsert helpers
  analytics/    (empty — session 2)
  mcp_server/   (empty — session 5)
  cli.py        argparse entry point (`uv run catch ...`)
  main.py       FastAPI app factory
web/
  src/
    components/ ui/ (Card, Badge, Skeleton, …), today/ (RecoveryRing, StrainGauge, …),
                shell/ (AppShell, Sidebar, BottomNav)
    lib/        api.ts (fetch + mock switch), types.ts (hand-kept in sync with the API —
                no codegen), mock.ts (?mock=1/calibrating/empty/error/loading fixtures),
                format.ts, auth.tsx, theme.tsx
    pages/      Today.tsx; Workouts/Trends/Coach/Settings are placeholders until session 4
    styles/     tokens.css — design tokens as CSS vars, see /DESIGN.md
tests/          fixtures/ has recorded JSON; no live network calls in the suite
docs/           garmin-endpoints.md, withings-endpoints.md, garmin-openapi.json, analytics.md
DESIGN.md       palette/type/motion decisions for the web frontend
```

## Commands

- `uv sync` — install deps
- `uv run catch sync --source garmin --days 30` — sync one source
- `uv run catch backfill` — backfill `BACKFILL_DAYS` from `.env`
- `uv run uvicorn catch.main:app --reload --port $CATCH_PORT` — dev server (port comes from `.env`)
- `uv run pytest` — tests (fixtures only, never hits live APIs)
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
