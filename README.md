# Catch

[![CI](https://github.com/Bean91/catch/actions/workflows/ci.yml/badge.svg)](https://github.com/Bean91/catch/actions/workflows/ci.yml)

> **DISCLAIMER:** This app was *fully* vibe-coded, so if you find any bugs, let me know. Feel free to fork this repo and make your own edits. I have more plans for expanding this in the future, and I will upload my prompt pack soon.

Self-hosted, single-user rowing training app. Garmin + Withings + Concept2 data, Whoop-style
recovery/strain, an AI coach (bring-your-own Anthropic key or a local Ollama model) with a
shared MCP server for Claude Desktop. Designed to run 24/7 on a Raspberry Pi 3 alongside
PiAware, but works just as well as a local dev instance on your laptop.

See `CLAUDE.md` for the full stack/layout/conventions, `docs/analytics.md` for the
recovery/strain/load math, and `docs/mcp.md` for Claude Desktop + MCP setup.

## 1. Prerequisites

- Python 3.12 (managed via [`uv`](https://docs.astral.sh/uv/) — you don't need Python
  preinstalled, `uv` fetches it)
- Node.js (build-time only, for the frontend — the app itself never runs Node at runtime)
- A Garmin Connect account with a [Personal API
  key](https://developer.garmin.com/gc-developer-program/personal)
- A Withings developer account + app ([developer.withings.com](https://developer.withings.com))
  if you want body composition data
- A Concept2 Logbook account + personal access token if you row on an erg
- (Optional) an Anthropic API key, or a local [Ollama](https://ollama.com) install, for the AI
  coach

## 2. Local setup

```bash
git clone <this repo> catch && cd catch
uv sync
cp .env.example .env
```

Fill in `.env`:

- `CATCH_PASSWORD_HASH` — `python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('yourpassword'))"`
- `CATCH_SESSION_SECRET` — `python -c "import secrets; print(secrets.token_hex(32))"`
- `CATCH_FERNET_KEY` — `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `GARMIN_PERSONAL_API_KEY` — from the Garmin developer page above
- `WITHINGS_CLIENT_ID` / `WITHINGS_CLIENT_SECRET` — from your Withings developer app
- `WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET` / `WHOOP_REDIRECT_URI` — optional, from your Whoop developer app (see `docs/whoop-endpoints.md`)
- `CATCH_SECRETS_MASTER_KEY` — optional on the Pi (falls back to `CATCH_FERNET_KEY`); protects your AI provider keys (see `docs/security.md`)
- `CONCEPT2_ACCESS_TOKEN` — Concept2 Logbook > Edit Profile > Applications

Every key is documented inline in `.env.example`.

```bash
uv run pytest                 # fixture-based test suite, no live network calls
uv run catch sync --source garmin --days 30
uv run catch backfill         # backfills BACKFILL_DAYS from .env, all sources
uv run uvicorn catch.main:app --reload --port $CATCH_PORT
```

Withings needs one manual OAuth step the first time — see "Completing the OAuth flow
manually" in `docs/withings-endpoints.md`.

### Frontend

```bash
cd web
npm install
npm run dev          # Vite dev server, proxies /api and /auth to CATCH_PORT
# or, with no backend running at all:
npm run dev -- --open  # then visit with ?mock=1 appended to the URL
```

`npm run build` builds to `catch/api/static`, which FastAPI serves at `/` in production. It's
gitignored — build it fresh for each deploy, never commit it.

## 3. Deploying to a Raspberry Pi (or any always-on Linux box)

The included `deploy/` scripts assume a Pi reachable over SSH and already (or about to be) on
[Tailscale](https://tailscale.com). They build the frontend on your laptop — never on the
Pi — and were written/verified against a real Raspberry Pi 3 (aarch64, Debian 13) that also
runs [PiAware](https://flightaware.com/adsb/piaware/) and
[FlightRadar24's feeder](https://www.flightradar24.com/) side by side; every step is scoped to
avoid touching those services, their ports, or their systemd units.

**One-time setup** (run once, interactively, with your own `sudo` password — never shared with
any tooling here):

```bash
rsync -a deploy/ your-pi-host:/tmp/catch-deploy/
ssh -t your-pi-host 'sudo sh /tmp/catch-deploy/pi-bootstrap.sh'
```

This creates a dedicated `catch` system user (no login shell, no home dir), `/opt/catch` (code)
and `/var/lib/catch` (DB, FIT files, secrets, nightly backups — all outside the code directory
so a redeploy's `rsync --delete` can never touch them), installs `sqlite3`, the `catch.service`
/ `catch-backup.timer` systemd units, a journald size cap, a narrowly-scoped sudoers rule
(just `systemctl restart/is-active/status catch.service`, nothing else, so routine deploys
never need a password), and turns on `tailscale serve` for HTTPS. It's idempotent — re-run it
any time you change a file under `deploy/`.

It also checks whether the kernel's memory cgroup controller is enabled (Raspberry Pi OS ships
it compiled in but off by default) — if not, it edits `/boot/firmware/cmdline.txt` (backing up
the original first) and reboots, which is the only step that briefly interrupts anything else
on the box, including PiAware. Without this, `catch.service`'s `MemoryMax=300M` would be
silently unenforced.

Then put real secrets in place. Copy `deploy/catch.env.example` to
`/var/lib/catch/catch.env` on the Pi (mode `600`, owned by `catch`), filling in the same
values your local `.env` has, plus Pi-specific absolute paths and your Tailscale hostname —
the file is commented with exactly what differs.

**Every deploy after that:**

```bash
./deploy.sh
```

Builds the frontend, rsyncs `catch/`, `pyproject.toml`, and `uv.lock` to the Pi (never your
`.env`/DB — those live outside the synced directory), runs `uv sync` there, restarts
`catch.service`, and polls `/api/health` until it responds (cold start on a Pi 3 takes
15-20 seconds).

### Backups

A systemd timer runs `sqlite3 .backup` nightly (03:30, randomized ±20min), integrity-checks
the copy (`PRAGMA integrity_check`), keeps the 14 most recent snapshots in
`/var/lib/catch/backups/`, and (if `BACKUP_SCP_TARGET` is set — see `.env.example`) scp's the
newest one to a laptop over Tailscale, keeping 30 there. A dead-man's-switch ping
(`HEALTHCHECKS_BACKUP_URL`) and an ntfy alert on a real failure are both optional — see
`.env.example`. Current status (last backup time/size, integrity, off-Pi copy) is on the
Status page (Settings → Status). Pull backups to your laptop manually any time with:

```bash
./deploy/pull-backups.sh [destination-dir]
```

### Withings callback over Tailscale

Once `tailscale serve` is live, re-register your Withings app's callback URL to
`https://<pi-name>.<tailnet>.ts.net/auth/withings/callback` — see "Callback URL on the Pi
deployment" in `docs/withings-endpoints.md` for the full detail, including why this only works
from a device on your own tailnet (not the public internet).

### Garmin key expiry

Garmin's API exposes no key-expiry field, so there's nothing to poll — instead, set the
"Garmin personal API key expires on" date in Settings once you create a key. A banner appears
across the whole app (not just Settings) once 14 days or fewer remain, linking straight to
Garmin's key management page.

## 4. The AI coach + MCP server

See `docs/mcp.md` for wiring Claude Desktop up to Catch's shared tool registry over Tailscale,
including how to mint a device token and what each of the 16 tools does. The in-app coach
(Settings > AI coach) works with either a bring-your-own Anthropic key or a local Ollama
instance on your own machine — Ollama can't run on a Pi 3, so point `CATCH_BASE_URL` at your
laptop's Ollama if you go that route.

## 5. Project layout

See `CLAUDE.md` for the full directory breakdown and engineering conventions (upsert
semantics, Garmin/Withings field-mapping rules, Pi memory constraints, etc.).

## 6. Before pushing (a note to future-me)

Run `make check` first — it's the exact same commands `.github/workflows/ci.yml` runs
(Python: `ruff` + `pytest`; frontend: typecheck, lint, Vitest, a production build, the
250 KB-gzip bundle-size budget, then the full Playwright suite against that build). Nothing
in CI needs secrets — everything runs on fixtures/mocks, never a live API — so a failure on
GitHub always reproduces locally. `deploy.sh` also refuses to run if `make check` fails or the
working tree is dirty, so there's no faster path to a bad deploy than just fixing it here first.
