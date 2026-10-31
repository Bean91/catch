# Catch

Self-hosted, single-user rowing training app. Garmin + Withings + Concept2 data, Whoop-style
recovery/strain, AI coach later. Runs 24/7 on a Raspberry Pi 3 (1GB RAM, ARM) alongside PiAware.

## Stack

Python 3.12 via `uv`, FastAPI + uvicorn, SQLModel on SQLite (WAL mode), httpx, APScheduler
3.x, pytest, `cryptography` (Fernet), `argon2-cffi` (verify the password hash already in
`.env`). Frontend (later): React + Vite + TS, built to static files, served by FastAPI.
No Docker, no Postgres, no Redis, no Node at runtime.

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
web/            (empty — frontend comes later)
tests/          fixtures/ has recorded JSON; no live network calls in the suite
docs/           garmin-endpoints.md, withings-endpoints.md, garmin-openapi.json
```

## Commands

- `uv sync` — install deps
- `uv run catch sync --source garmin --days 30` — sync one source
- `uv run catch backfill` — backfill `BACKFILL_DAYS` from `.env`
- `uv run uvicorn catch.main:app --reload --port $CATCH_PORT` — dev server (port comes from `.env`)
- `uv run pytest` — tests (fixtures only, never hits live APIs)

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
