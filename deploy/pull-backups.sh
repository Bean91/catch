#!/usr/bin/env bash
# Pulls the Pi's nightly SQLite backups down to the laptop. Read-only on the Pi side —
# relies on pi-bootstrap.sh having added `opensky` to the `catch` group so these
# catch-owned, mode-640 files are actually readable over this rsync.
set -euo pipefail

HOST=opensky-pi
DEST=${1:-./backups-from-pi}

mkdir -p "$DEST"
rsync -az "$HOST:/var/lib/catch/backups/" "$DEST/"
echo "==> Backups now in $DEST:"
ls -la "$DEST"
