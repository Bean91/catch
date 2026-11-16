from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.core import tenant
from catch.core.config import settings
from catch.sync import connections
from catch.core.settings_store import get_settings
from catch.core.uptime import START_TIME

router = APIRouter(dependencies=[Depends(require_auth)])

# Matches deploy/backup.sh's hardcoded BACKUP_DIR (/var/lib/catch/backups, i.e. a `backups`
# subdir next to the DB) without needing its own env var — CATCH_DB_PATH already points at
# the right parent directory in both dev (data/catch.db) and production
# (/var/lib/catch/catch.db).
_BACKUP_STATUS_FILE = Path(settings.db_file).parent / "backups" / "status.json"
_VERSION_FILE = Path(__file__).resolve().parent / "static" / "version.json"


def _backup_status() -> dict | None:
    if not _BACKUP_STATUS_FILE.is_file():
        return None
    try:
        return json.loads(_BACKUP_STATUS_FILE.read_text())
    except (OSError, ValueError):
        return None


def _build_info() -> dict | None:
    if not _VERSION_FILE.is_file():
        return None
    try:
        return json.loads(_VERSION_FILE.read_text())
    except (OSError, ValueError):
        return None


def _db_size_bytes() -> int:
    db_path = Path(settings.db_file)
    total = 0
    for suffix in ("", "-wal", "-shm"):
        candidate = db_path.with_name(db_path.name + suffix)
        if candidate.is_file():
            total += candidate.stat().st_size
    return total


@router.get("/api/status")
def status(db: Session = Depends(get_db)):
    sources = [
        {
            "source": card["provider"],
            "last_success_at": card["last_success_at"],
            "last_attempt_at": card["last_attempt_at"],
            "last_error": card["last_error"],
            "consecutive_failures": card["consecutive_failures"],
            "token_expires_at": card["token_expires_at"],
            "connected": card["connected"],
            "status": card["status"],
        }
        for card in connections.list_cards(db)
    ]
    garmin = connections.get(db, "garmin")

    app_settings = get_settings(db)
    # A per-user connection owns its key expiry; the Pi's settings row remains the fallback for a key kept in .env.
    garmin_expiry = garmin.credential_expires_on.isoformat() if garmin and garmin.credential_expires_on else app_settings.get("garmin_key_expires_on")
    if tenant.is_public():
        # Disk, database size, uptime and backup state describe the shared server — not something one user may read.
        return {
            "sources": sources, "garmin_key_expires_on": garmin_expiry, "backup": None, "disk_free_bytes": 0, "disk_total_bytes": 0,
            "db_size_bytes": 0, "uptime_seconds": 0, "build": _build_info(),
        }
    disk = shutil.disk_usage(Path(settings.db_file).parent)

    return {
        "sources": sources,
        "garmin_key_expires_on": garmin_expiry,
        "backup": _backup_status(),
        "disk_free_bytes": disk.free,
        "disk_total_bytes": disk.total,
        "db_size_bytes": _db_size_bytes(),
        "uptime_seconds": (datetime.now(timezone.utc) - START_TIME).total_seconds(),
        "build": _build_info(),
    }
