#!/usr/bin/env bash
# One-shot production fix-up after the session 31 audit: backup -> migrate -> build -> deploy -> smoke.
# Order matters: the database must be upgraded BEFORE the new code is deployed (launch audit B-1).
set -euo pipefail

REF=zgprcdkrxrrhscfqwbdx
POOLER=aws-1-us-east-2.pooler.supabase.com   # session pooler; the direct db.<ref> host is IPv6-only on Free
SUPABASE_URL="https://$REF.supabase.co"
PUBLISHABLE_KEY=sb_publishable_fijjzZmcedDHgsiF7Xzajw_LTs3CLCE
SITE=https://catch.openoted.com
BACKUP_DIR="$HOME/catch-backups"

cd "$(dirname "$0")/.."
step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

step "Checking out main"
[ "$(git branch --show-current)" = main ] || git checkout main
git diff --quiet || { echo "Uncommitted changes; aborting."; exit 1; }

step "Installing Python deps"
uv sync --extra public

read -rsp "Supabase database password (input hidden): " PW; echo
ENC_PW=$(PW="$PW" python3 -c 'import os,urllib.parse;print(urllib.parse.quote(os.environ["PW"],safe=""))')
unset PW
export DATABASE_ADMIN_URL="postgresql://postgres.$REF:$ENC_PW@$POOLER:5432/postgres?sslmode=require"

step "Backing up the database first ($BACKUP_DIR)"
mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
DUMP="$BACKUP_DIR/catch-$(date +%F-%H%M).dump"
pg_dump "$DATABASE_ADMIN_URL" -Fc -n catch -n catch_private -n catch_club -f "$DUMP"
chmod 600 "$DUMP"; ls -lh "$DUMP"

step "Migrating the database"
uv run catch db current
uv run catch db upgrade
uv run catch db current
unset DATABASE_ADMIN_URL ENC_PW

step "Building the frontend"
(cd web && npm ci && VITE_CATCH_DEPLOYMENT=public VITE_SUPABASE_URL="$SUPABASE_URL" \
  VITE_SUPABASE_PUBLISHABLE_KEY="$PUBLISHABLE_KEY" npm run build && npm run check:build-secrets)

step "Deploying to FastAPI Cloud"
uv run fastapi deploy

step "Waiting for $SITE/api/health"
for _ in $(seq 1 30); do curl -fsS "$SITE/api/health" >/dev/null 2>&1 && break; sleep 5; done
curl -fsS "$SITE/api/health"; echo

step "Production smoke test"
SMOKE_BASE_URL="$SITE" SMOKE_SUPABASE_URL="$SUPABASE_URL" SMOKE_PUBLISHABLE_KEY="$PUBLISHABLE_KEY" \
SMOKE_SECRET_KEY_FILE="$HOME/.catch-smoke-secret" uv run python scripts/smoke_public.py

step "Done. Backup saved at $DUMP"
