from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from catch.api.deps import get_db, require_auth
from catch.core import tenant
from catch.core.config import settings
from catch.core.models import OAuthToken, SyncState
from catch.core.settings_store import get_settings
from catch.core.uptime import START_TIME
from catch.sync.scheduler import SOURCES

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
    sync_rows = {row.source: row for row in db.exec(select(SyncState)).all()}
    token_rows = {row.source: row for row in db.exec(select(OAuthToken)).all()}
    sources = []
    for source in SOURCES:
        row = sync_rows.get(source)
        sources.append(
            {
                "source": source,
                "last_success_at": row.last_success_at if row else None,
                "last_attempt_at": row.last_attempt_at if row else None,
                "last_error": row.last_error if row else None,
                "consecutive_failures": row.consecutive_failures if row else 0,
                "token_expires_at": (token_rows.get(source).expires_at if token_rows.get(source) else None),
            }
        )

    app_settings = get_settings(db)
    if tenant.is_public():
        # Disk, database size, uptime and backup state describe the shared server — not something one user may read.
        return {
            "sources": sources, "garmin_key_expires_on": None, "backup": None, "disk_free_bytes": 0, "disk_total_bytes": 0,
            "db_size_bytes": 0, "uptime_seconds": 0, "build": _build_info(),
        }
    disk = shutil.disk_usage(Path(settings.db_file).parent)

    return {
        "sources": sources,
        "garmin_key_expires_on": app_settings.get("garmin_key_expires_on"),
        "backup": _backup_status(),
        "disk_free_bytes": disk.free,
        "disk_total_bytes": disk.total,
        "db_size_bytes": _db_size_bytes(),
        "uptime_seconds": (datetime.now(timezone.utc) - START_TIME).total_seconds(),
        "build": _build_info(),
    }
