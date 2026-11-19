"""The Privacy center API (session 28): a summary of what is held and what is public, a complete export, and category-level deletion.

Cookie / bearer-JWT only (a device token never reaches these). Everything is scoped to the caller by the tenant filter; the only
reads of another table family go through account_store's owner-column readers."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.api.ratelimit import rate_limit, throttle
from catch.coach import limits
from catch.core import tenant
from catch.core.owner import current_owner_id
from catch.sync import privacy

router = APIRouter(dependencies=[Depends(require_auth)])
EXPORTS_PER_DAY = 3


class ConfirmBody(BaseModel):
    confirm: bool = False


@router.get("/api/privacy/summary")
def get_summary(db: Session = Depends(get_db)):
    return privacy.summary(db)


@router.get("/api/privacy/tool-calls")
def tool_calls(limit: int = 100, db: Session = Depends(get_db)):
    """What outside clients (MCP, REST) and the in-app coach's writes have done through the tool layer — never the arguments or results."""
    from sqlmodel import select

    from catch.core.models import ToolCallLog

    rows = db.exec(select(ToolCallLog).order_by(ToolCallLog.id.desc()).limit(max(1, min(limit, 500)))).all()  # type: ignore[attr-defined]
    return [{"tool": r.tool, "via": r.via, "as": r.principal_kind, "write": r.is_write, "confirmed": r.confirmed, "outcome": r.outcome, "at": r.created_at} for r in rows]


@router.get("/api/privacy/export", dependencies=[rate_limit("export")])
def export_everything(owner_id: str = Depends(current_owner_id)):
    try:
        limits.check_daily(owner_id, "export", EXPORTS_PER_DAY)
    except limits.LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.message, headers={"Retry-After": str(exc.retry_after_s)}) from None
    name = f"catch-export-{datetime.now(timezone.utc).strftime('%Y%m%d')}.ndjson.gz"
    return StreamingResponse(
        privacy.iter_export(owner_id),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


@router.delete("/api/privacy/data/{category}")
def delete_data(category: str, body: ConfirmBody, request: Request, db: Session = Depends(get_db)):
    throttle("account")
    if category not in privacy.DELETE_CATEGORIES:
        raise HTTPException(status_code=404, detail="Unknown category")
    if body.confirm is not True:
        raise HTTPException(status_code=400, detail='Send {"confirm": true} to delete this data')
    files = 0
    if category == "media" and tenant.is_public():
        from catch.api import routes_account

        token = request.headers["authorization"][len("bearer ") :].strip()
        try:
            files = routes_account.purge_storage(token, tenant.current_owner())
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Could not remove stored files; nothing was deleted — try again") from None
    return {**privacy.delete_category(db, category), "files_removed": files}
