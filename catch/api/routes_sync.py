from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from catch.api.deps import get_db, require_auth
from catch.core.models import OAuthToken, SyncState
from catch.sync.scheduler import SOURCES, run_sync

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/api/sync/{source}")
def trigger_sync(source: str):
    if source not in SOURCES:
        raise HTTPException(status_code=404, detail=f"Unknown source: {source}")
    return run_sync(source)


@router.get("/api/sync/status")
def sync_status(db: Session = Depends(get_db)):
    sync_rows = {row.source: row for row in db.exec(select(SyncState)).all()}
    # Concept2 has no OAuthToken row (static long-lived personal access token, no exchange/
    # refresh step) — token_expires_at stays null there, which is correct, not missing data.
    token_rows = {row.source: row for row in db.exec(select(OAuthToken)).all()}
    out = []
    for source in SOURCES:
        base = sync_rows.get(source) or {"source": source, "last_success_at": None, "last_error": None}
        base = base.model_dump() if hasattr(base, "model_dump") else dict(base)
        token = token_rows.get(source)
        base["token_expires_at"] = token.expires_at if token else None
        out.append(base)
    return out
