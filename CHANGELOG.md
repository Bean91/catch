# Changelog

Releases are tagged only when docs/release-checklist.md passes. Until then this file records what landed on the way.

## Unreleased: session 31 launch audit (2026-11-20)

Launch status: **NO-GO**. Blockers are listed in docs/launch-audit.md.

### Fixed
- Account deletion and other endpoints returned 500 when the database was behind the deployed code. The app now detects this
  (startup ERROR and `/internal/db-check` `schema_missing_tables`); production needs `catch db upgrade`.
- Withings `Invalid HMAC signature` from a secret stored with a trailing newline: environment values are now trimmed.
- `?mock=1` showed a fake signed-in app on the public site.
- The public Status page showed false zero disk, database, uptime and backup figures.
- Leaderboards past 5000 entries dropped arbitrary rows before ranking.
- Bad `/internal` secrets could rate-limit the real scheduled tick. One user's failure could stop a tick or hold a lease.
- MCP connectors that only refresh their token were deleted after 30 days.
- Weather refresh failed on Postgres (migration 0010).
- A person's "not a duplicate" / "split" decisions were pruned after 400 days.
- Recovery scored a day from prior strain alone; a missing kcal counted as 0; under-fuelling counted today's partial day and
  unknown-kcal foods; piece average split averaged split durations.
- The metric/imperial toggle that did nothing was removed; unavailable sources and public-only pages are hidden on builds that
  can't use them.

### Added
- Migration 0010.
- `scripts/mcp_stdio_check.py`, `scripts/load_local.py` and `scripts/backup_restore_drill.py`.
- Launch documents: launch-audit, release-checklist, operations-runbook, mcp-client-setup, supabase-setup and
  fastapi-cloud-deployment.

## v1.0 (2026-11-01)
- "deployed to the real Raspberry Pi" — the personal (Pi) build as of commit 2f1e1d8 (before the public deployment).
