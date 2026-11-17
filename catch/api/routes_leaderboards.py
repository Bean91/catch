"""Session 26 (docs/leaderboards.md): leaderboards, publishing, reports, appeals, clubs. Public deployment only, signed-in
users only (cookie/JWT — never a device token). Every other-user read goes through catch.sync.leaderboards, which renders
through the one public serializer."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.coach import limits
from catch.core import tenant
from catch.sync import leaderboard_store as store
from catch.sync import leaderboards as svc


def public_only() -> None:
    if not tenant.is_public():
        raise HTTPException(status_code=404, detail="Leaderboards are only available on the public deployment")


router = APIRouter(dependencies=[Depends(public_only), Depends(require_auth)])


def _throttle(bucket: str = "leaderboard") -> None:
    try:
        limits.check_rate(tenant.current_owner(), bucket)
    except limits.LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.message) from None


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (svc.LeaderboardError, store.StoreError) as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


class Ref(BaseModel):
    kind: str
    id: int


class Prefs(BaseModel):
    show_age_band: Optional[bool] = None
    show_weight_class: Optional[bool] = None
    date_precision: Optional[str] = None
    note: Optional[str] = None
    note_public: bool = False


class PreviewBody(BaseModel):
    ref: Ref
    prefs: Prefs = Field(default_factory=Prefs)


class PublishBody(PreviewBody):
    confirm: bool = False
    preview_hash: str = ""


class SettingsBody(BaseModel):
    handle: Optional[str] = None
    display_mode: Optional[str] = None
    date_precision: Optional[str] = None
    show_age_band: Optional[bool] = None
    show_weight_class: Optional[bool] = None
    self_declared_band: Optional[str] = None
    attest_min_age: Optional[bool] = None
    attest_guardian: Optional[bool] = None


class OptInBody(SettingsBody):
    confirm: bool = False


class ConfirmBody(BaseModel):
    confirm: bool = False


class NoteBody(BaseModel):
    note: Optional[str] = None
    note_public: Optional[bool] = None


class ReportBody(BaseModel):
    reason: str
    detail: Optional[str] = None


class AppealBody(BaseModel):
    text: str


class ClubBody(BaseModel):
    name: str


class JoinBody(BaseModel):
    code: str


@router.get("/api/leaderboards/boards")
def list_boards():
    return {"boards": svc.board_list(), "age_bands": list(svc.lb.AGE_LABELS)}


@router.get("/api/leaderboards/me")
def me(db: Session = Depends(get_db)):
    return _call(svc.my_state, db)


@router.put("/api/leaderboards/me/settings")
def put_settings(body: SettingsBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.update_settings, db, body.model_dump(exclude_unset=True))


@router.post("/api/leaderboards/me/opt-in")
def post_opt_in(body: OptInBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.opt_in, db, body.model_dump(exclude_unset=True))


@router.post("/api/leaderboards/me/opt-out")
def post_opt_out(body: ConfirmBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.opt_out, db, body.model_dump())


@router.get("/api/leaderboards/me/results")
def my_results(board: Optional[str] = None, state: Optional[str] = None, db: Session = Depends(get_db)):
    return {"results": _call(svc.my_results, db, board=board, state=state)}


@router.get("/api/leaderboards/me/profile-preview")
def profile_preview(db: Session = Depends(get_db)):
    return _call(svc.my_profile_preview, db)


@router.get("/api/leaderboards/me/moderation")
def my_moderation():
    owner = tenant.current_owner()
    return {"events": store.my_events(owner), "appeals": store.my_appeals(owner)}


@router.post("/api/leaderboards/publications/preview")
def preview(body: PreviewBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.preview, db, body.ref.model_dump(), body.prefs.model_dump())


@router.post("/api/leaderboards/publications")
def publish(body: PublishBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.publish, db, body.ref.model_dump(), body.prefs.model_dump(), confirm=body.confirm, preview_hash=body.preview_hash)


@router.patch("/api/leaderboards/publications/{entry_id}")
def patch_publication(entry_id: str, body: NoteBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.update_publication, db, entry_id, body.model_dump(exclude_unset=True))


@router.post("/api/leaderboards/publications/{entry_id}/withdraw")
def withdraw(entry_id: str, body: ConfirmBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.unpublish, db, entry_id, confirm=body.confirm)


@router.get("/api/leaderboards/boards/{board_key}")
def get_board(board_key: str, age: Optional[str] = None, weight: Optional[str] = None, club: Optional[str] = None,
              verification: str = "verified", offset: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.board, db, board_key, age=age, weight=weight, club=club, verification=verification, offset=offset, limit=limit)


@router.get("/api/leaderboards/athletes/{athlete_id}")
def get_athlete(athlete_id: str):
    _throttle()
    return _call(svc.athlete_profile, athlete_id)


@router.post("/api/leaderboards/entries/{entry_id}/report")
def report(entry_id: str, body: ReportBody, db: Session = Depends(get_db)):
    _throttle("report")
    return _call(svc.report_entry, db, entry_id, body.reason, body.detail)


@router.post("/api/leaderboards/entries/{entry_id}/appeal")
def appeal(entry_id: str, body: AppealBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.appeal_entry, db, entry_id, body.text)


@router.post("/api/leaderboards/appeals/{appeal_id}/withdraw")
def withdraw_appeal(appeal_id: int):
    return _call(store.withdraw_appeal, tenant.current_owner(), appeal_id) or {"withdrawn": True}


@router.post("/api/leaderboards/clubs")
def create_club(body: ClubBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.create_club, db, body.name)


@router.post("/api/leaderboards/clubs/join")
def join_club(body: JoinBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.join_club, db, body.code)


@router.delete("/api/leaderboards/clubs/{club_id}")
def leave_club(club_id: str, db: Session = Depends(get_db)):
    return _call(svc.leave_club, db, club_id)
