#!/bin/sh
# Nightly SQLite backup, installed by pi-bootstrap.sh to /usr/local/bin/catch-backup.sh and
# run by catch-backup.timer as the `catch` user. sqlite3 .backup is safe against a running
# WAL-mode writer (it's the same mechanism the sqlite3 CLI's online backup API always uses),
# so this never stops or pauses the app.
set -eu

DB=/var/lib/catch/catch.db
BACKUP_DIR=/var/lib/catch/backups
KEEP=14

mkdir -p "$BACKUP_DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$BACKUP_DIR/catch-$STAMP.db"

sqlite3 "$DB" ".backup '$OUT'"
chmod 640 "$OUT"

# Lexical sort == chronological order for this timestamp format, so the oldest files are
# simply everything past the first $KEEP in a newest-first listing.
ls -1t "$BACKUP_DIR"/catch-*.db 2>/dev/null | tail -n +"$((KEEP + 1))" | while IFS= read -r stale; do
    rm -f "$stale"
done
