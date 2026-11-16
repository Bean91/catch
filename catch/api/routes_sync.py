from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.core.models import SyncState
from catch.sync import connections
from catch.sync.scheduler import SOURCES, run_sync

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/api/sync/{source}")
def trigger_sync(source: str):
    if source not in SOURCES:
        raise HTTPException(status_code=404, detail=f"Unknown source: {source}")
    return run_sync(source, manual=True)


@router.get("/api/sync/status")
def sync_status(db: Session = Depends(get_db)):
    from catch.core import tenant

    out = []
    for card in connections.list_cards(db):
        row = db.get(SyncState, tenant.pk(card["provider"]))
        out.append(
            {
                "source": card["provider"],
                "cursor": row.cursor if row else None,
                "last_attempt_at": row.last_attempt_at if row else None,
                "last_success_at": row.last_success_at if row else None,
                "last_error": row.last_error if row else None,
                "consecutive_failures": row.consecutive_failures if row else 0,
                "alert_sent_at": row.alert_sent_at if row else None,
                # Concept2 personal tokens and Garmin keys have no OAuth expiry: null there is correct, not missing data.
                "token_expires_at": card["token_expires_at"],
                "connected": card["connected"],
                "status": card["status"],
                "status_text": card["status_text"],
                "importing_history_from": card["importing_history_from"],
                "credential_expires_on": card["credential_expires_on"],
            }
        )
    return out
