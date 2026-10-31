from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from catch.api.deps import get_db, require_auth
from catch.core.models import SyncState
from catch.sync.scheduler import SOURCES, run_sync

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/api/sync/{source}")
def trigger_sync(source: str):
    if source not in SOURCES:
        raise HTTPException(status_code=404, detail=f"Unknown source: {source}")
    return run_sync(source)


@router.get("/api/sync/status")
def sync_status(db: Session = Depends(get_db)):
    rows = db.exec(select(SyncState)).all()
    by_source = {row.source: row for row in rows}
    return [
        by_source.get(source) or {"source": source, "last_success_at": None, "last_error": None}
        for source in SOURCES
    ]
