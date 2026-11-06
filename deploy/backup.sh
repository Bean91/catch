#!/bin/sh
# Nightly SQLite backup, installed by pi-bootstrap.sh to /usr/local/bin/catch-backup.sh and
# run by catch-backup.timer as the `catch` user. sqlite3 .backup is safe against a running
# WAL-mode writer (it's the same mechanism the sqlite3 CLI's online backup API always uses),
# so this never stops or pauses the app.
#
# Session 16 (see PLAN.md Part B.4): integrity-checks the copy, pings healthchecks.io
# (HEALTHCHECKS_BACKUP_URL, read from /var/lib/catch/catch.env via catch-backup.service's
# EnvironmentFile=), alerts via ntfy on a real failure, and scp's the newest backup to a
# laptop over Tailscale (BACKUP_SCP_TARGET, e.g. "ben@ben-macbook.tailnet.ts.net:/Users/ben/
# catch-backups/") whenever that laptop happens to be reachable. A laptop that's asleep at
# 03:30 is the common case, not a failure — it's skipped silently (no /fail ping, no ntfy),
# and simply tried again the next night. There is deliberately no separate hourly retry timer
# for this — the task asks for a nightly copy "when reachable," not guaranteed-eventual
# delivery, and a missed night is visible on the Status page regardless.
set -eu

: "${DB:=/var/lib/catch/catch.db}"
: "${BACKUP_DIR:=/var/lib/catch/backups}"
: "${SSH_KEY:=/var/lib/catch/.ssh/id_ed25519}"
KEEP=14
REMOTE_KEEP=30
STATUS_FILE="$BACKUP_DIR/status.json"

: "${HEALTHCHECKS_BACKUP_URL:=}"
: "${NTFY_TOPIC:=}"
: "${BACKUP_SCP_TARGET:=}"

hc_ping() {
    # "$1" is "" for the success ping or "/fail" — healthchecks.io's own convention.
    [ -n "$HEALTHCHECKS_BACKUP_URL" ] && curl -fsS -m 10 "$HEALTHCHECKS_BACKUP_URL$1" >/dev/null 2>&1
    return 0
}

ntfy() {
    [ -n "$NTFY_TOPIC" ] && curl -fsS -m 10 -X POST -d "$1" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null 2>&1
    return 0
}

# dash (this script's shebang) has no `trap ... ERR` — every risky step below calls this
# explicitly on failure instead, which is both more portable and makes exactly what counts as
# "the backup failed" an explicit, readable list rather than implicit trap magic.
fail() {
    echo "catch-backup: $1" >&2
    hc_ping /fail
    ntfy "Catch backup FAILED: $1"
    exit 1
}

mkdir -p "$BACKUP_DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$BACKUP_DIR/catch-$STAMP.db"

sqlite3 "$DB" ".backup '$OUT'" || fail "sqlite3 .backup failed"
chmod 640 "$OUT"

INTEGRITY=$(sqlite3 "$OUT" "PRAGMA integrity_check;" 2>&1) || fail "integrity_check errored: $INTEGRITY"
[ "$INTEGRITY" = "ok" ] || fail "integrity_check reported: $INTEGRITY"

SIZE=$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT")
NOW_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Lexical sort == chronological order for this timestamp format, so the oldest files are
# simply everything past the first $KEEP in a newest-first listing.
ls -1t "$BACKUP_DIR"/catch-*.db 2>/dev/null | tail -n +"$((KEEP + 1))" | while IFS= read -r stale; do
    rm -f "$stale"
done

REMOTE_COPIED_AT=null
REMOTE_OK=null
if [ -n "$BACKUP_SCP_TARGET" ] && [ -f "$SSH_KEY" ]; then
    SSH_HOST=${BACKUP_SCP_TARGET%%:*}
    REMOTE_PATH=${BACKUP_SCP_TARGET#*:}
    if ssh -o BatchMode=yes -o ConnectTimeout=10 -i "$SSH_KEY" "$SSH_HOST" true 2>/dev/null; then
        if scp -o BatchMode=yes -i "$SSH_KEY" "$OUT" "$BACKUP_SCP_TARGET" >/dev/null 2>&1; then
            REMOTE_COPIED_AT="\"$NOW_ISO\""
            REMOTE_OK=true
            # scp can't delete — prune the remote side over the same ssh connection. Best-
            # effort: a failure here doesn't fail the backup, since the copy itself
            # (the thing that matters) already succeeded.
            ssh -o BatchMode=yes -i "$SSH_KEY" "$SSH_HOST" \
                "cd \"$REMOTE_PATH\" 2>/dev/null && ls -1t catch-*.db 2>/dev/null | tail -n +\"\$(($REMOTE_KEEP + 1))\" | xargs -I{} rm -f {}" \
                2>/dev/null || true
        else
            REMOTE_COPIED_AT="\"$NOW_ISO\""
            REMOTE_OK=false
            ntfy "Catch backup: local copy OK, off-Pi scp to $SSH_HOST failed"
        fi
    fi
    # else: laptop unreachable right now — skipped, not a failure (see file header).
fi

# Temp file + mv (not a direct write) so the app never reads a half-written status.json.
TMP_STATUS="$STATUS_FILE.tmp"
printf '{"last_backup_at": "%s", "backup_size_bytes": %s, "integrity_ok": true, "remote_copied_at": %s, "remote_ok": %s}\n' \
    "$NOW_ISO" "$SIZE" "$REMOTE_COPIED_AT" "$REMOTE_OK" > "$TMP_STATUS"
mv "$TMP_STATUS" "$STATUS_FILE"
chmod 640 "$STATUS_FILE"

hc_ping ""
