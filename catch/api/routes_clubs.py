"""Session 27 (docs/clubs.md): clubs, team training, challenges, announcements, safety. Public deployment only, signed-in users only (cookie/JWT,
never a device token). Every route acts as the signed-in person over their own database session, so on Postgres each statement is also checked
by the membership RLS policies. Identity is `tenant.current_owner()`, set by `require_auth`; no route reads an owner from the body or query.

Static paths (`/mine`, `/discover`, `/profile`, `/join`, `/invite-preview`) are registered before `/{club_id}`: FastAPI matches in order."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import Session

from catch.api.deps import get_db, require_auth
from catch.api.routes_leaderboards import public_only
from catch.coach import limits
from catch.core import tenant
from catch.sync import club_challenges as challenges
from catch.sync import club_store as store
from catch.sync import club_team as team
from catch.sync import clubs as svc

router = APIRouter(prefix="/api/clubs", dependencies=[Depends(public_only), Depends(require_auth)])


def _throttle(bucket: str = "club") -> None:
    try:
        limits.check_rate(tenant.current_owner(), bucket)
    except limits.LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=exc.message) from None


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (svc.ClubError, store.StoreError) as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    except IntegrityError:
        raise HTTPException(status_code=409, detail="That conflicts with something that already exists.") from None
    except DBAPIError as exc:  # the database's own policy refused what the service let through: still a clean answer, never a 500
        if getattr(getattr(exc, "orig", None), "sqlstate", None) == "42501":
            raise HTTPException(status_code=403, detail="Your role in this club can't do that.") from None
        raise


class ProfileBody(BaseModel):
    handle: str
    age_band: str
    attest_min_age: bool = False
    guardian_consent: bool = False


class ClubBody(BaseModel):
    name: str
    description: Optional[str] = None
    location: Optional[str] = None
    visibility: str = "private"
    audience: str = "adult"
    join_policy: str = "request"
    rules: Optional[str] = None


class ClubPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    visibility: Optional[str] = None
    join_policy: Optional[str] = None
    rules: Optional[str] = None


class JoinBody(BaseModel):
    token: Optional[str] = None
    club_id: Optional[str] = None
    message: Optional[str] = None
    accept_rules: bool = False


class TokenBody(BaseModel):
    token: str


class ConfirmBody(BaseModel):
    confirm: bool = False


class TransferBody(BaseModel):
    member_ref: str
    confirm: bool = False


class RoleBody(BaseModel):
    role: str
    reason: Optional[str] = None


class ReasonBody(BaseModel):
    reason: str


class PrefsBody(BaseModel):
    include_public_results: Optional[bool] = None
    share_numbers: Optional[bool] = None
    accept_rules: bool = False


class InviteBody(BaseModel):
    role: str = "athlete"
    days: Optional[int] = None
    max_uses: Optional[int] = None


class DecideRequestBody(BaseModel):
    approve: bool
    reason: Optional[str] = None


class PostBody(BaseModel):
    title: str
    body: str


class DecidePostBody(BaseModel):
    action: str
    reason: Optional[str] = None


class SessionBody(BaseModel):
    title: str
    session_type: str = "other"
    date: date
    start_time: Optional[str] = None
    duration_min: Optional[int] = None
    distance_m: Optional[int] = None
    description: Optional[str] = None


class LinkBody(BaseModel):
    canonical_id: int
    share_numbers: Optional[bool] = None


class ChallengeBody(BaseModel):
    title: str
    metric: str
    start: date
    end: date
    goal: Optional[int] = None
    description: Optional[str] = None
    sport: str = "rowing"
    target_per_week: Optional[int] = None
    day_cap_m: Optional[int] = None
    day_cap_s: Optional[int] = None
    min_session_s: Optional[int] = None


class ExcuseBody(BaseModel):
    week: date
    excused: bool = True


class ResultBody(BaseModel):
    ref: dict = Field(default_factory=dict)
    note: Optional[str] = None


class ReportBody(BaseModel):
    target_type: str
    target_id: str = ""
    reason: str
    detail: Optional[str] = None


# ---------------------------------------------------------------- not scoped to one club

@router.get("/mine")
def mine(db: Session = Depends(get_db)):
    return _call(svc.my_clubs, db)


@router.get("/discover")
def discover(q: Optional[str] = None, limit: int = 30, db: Session = Depends(get_db)):
    return {"clubs": _call(svc.discover, db, q, limit)}


@router.get("/profile")
def get_profile(db: Session = Depends(get_db)):
    return _call(svc.get_profile, db)


@router.put("/profile")
def put_profile(body: ProfileBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.set_profile, db, handle=body.handle, age_band=body.age_band, attest_min_age=body.attest_min_age, guardian_consent=body.guardian_consent)


@router.post("")
def create_club(body: ClubBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.create_club, db, **body.model_dump())


@router.post("/join")
def join(body: JoinBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.join, db, token=body.token, club_id=body.club_id, message=body.message, accept_rules=body.accept_rules)


@router.post("/invite-preview")
def invite_preview(body: TokenBody, db: Session = Depends(get_db)):
    _throttle("report")  # a token is unguessable, but cap guessing anyway: 5 a minute
    return _call(svc.preview_invite, db, body.token)


@router.delete("/requests/{request_id}")
def withdraw_request(request_id: int, db: Session = Depends(get_db)):
    return _call(svc.withdraw_request, db, request_id)


# ---------------------------------------------------------------- one club

@router.get("/{club_id}")
def get_club(club_id: str, db: Session = Depends(get_db)):
    return _call(svc.get_club, db, club_id)


@router.patch("/{club_id}")
def update_club(club_id: str, body: ClubPatch, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.update_club, db, club_id, **body.model_dump(exclude_unset=True))


@router.post("/{club_id}/delete")
def delete_club(club_id: str, body: ConfirmBody, db: Session = Depends(get_db)):
    return _call(svc.delete_club, db, club_id, confirm=body.confirm)


@router.post("/{club_id}/leave")
def leave(club_id: str, db: Session = Depends(get_db)):
    return _call(svc.leave_club, db, club_id)


@router.post("/{club_id}/transfer")
def transfer(club_id: str, body: TransferBody, db: Session = Depends(get_db)):
    return _call(svc.transfer_ownership, db, club_id, body.member_ref, confirm=body.confirm)


@router.get("/{club_id}/members")
def members(club_id: str, db: Session = Depends(get_db)):
    return _call(svc.members, db, club_id)


@router.put("/{club_id}/members/{ref}/role")
def set_role(club_id: str, ref: str, body: RoleBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.set_role, db, club_id, ref, body.role, reason=body.reason)


@router.post("/{club_id}/members/{ref}/remove")
def remove_member(club_id: str, ref: str, body: ReasonBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.remove_member, db, club_id, ref, body.reason)


@router.put("/{club_id}/prefs")
def prefs(club_id: str, body: PrefsBody, db: Session = Depends(get_db)):
    return _call(svc.set_prefs, db, club_id, include_public_results=body.include_public_results, share_numbers=body.share_numbers, accept_rules=body.accept_rules)


@router.get("/{club_id}/invites")
def invites(club_id: str, db: Session = Depends(get_db)):
    return {"invites": _call(svc.list_invites, db, club_id)}


@router.post("/{club_id}/invites")
def create_invite(club_id: str, body: InviteBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.create_invite, db, club_id, role=body.role, days=body.days, max_uses=body.max_uses)


@router.post("/{club_id}/invites/{invite_id}/revoke")
def revoke_invite(club_id: str, invite_id: int, db: Session = Depends(get_db)):
    return _call(svc.revoke_invite, db, club_id, invite_id)


@router.get("/{club_id}/requests")
def requests(club_id: str, db: Session = Depends(get_db)):
    return {"requests": _call(svc.requests, db, club_id)}


@router.post("/{club_id}/requests/{request_id}/decide")
def decide_request(club_id: str, request_id: int, body: DecideRequestBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(svc.decide_request, db, club_id, request_id, approve=body.approve, reason=body.reason)


# ---------------------------------------------------------------- announcements, calendar, summary

@router.get("/{club_id}/announcements")
def announcements(club_id: str, db: Session = Depends(get_db)):
    return {"announcements": _call(team.announcements, db, club_id)}


@router.post("/{club_id}/announcements")
def post_announcement(club_id: str, body: PostBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(team.post_announcement, db, club_id, body.title, body.body)


@router.post("/{club_id}/posts/{kind}/{post_id}/decide")
def decide_post(club_id: str, kind: str, post_id: int, body: DecidePostBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(team.decide_post, db, club_id, kind, post_id, body.action, body.reason)


@router.get("/{club_id}/calendar")
def calendar(club_id: str, start: Optional[date] = None, end: Optional[date] = None, db: Session = Depends(get_db)):
    return _call(team.calendar, db, club_id, start, end)


@router.post("/{club_id}/sessions")
def create_session(club_id: str, body: SessionBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(team.create_session, db, club_id, title=body.title, session_type=body.session_type, on=body.date, start_time=body.start_time,
                 duration_min=body.duration_min, distance_m=body.distance_m, description=body.description)


@router.post("/{club_id}/sessions/{session_id}/participation")
def link_workout(club_id: str, session_id: int, body: LinkBody, db: Session = Depends(get_db)):
    return _call(team.link_workout, db, club_id, session_id, body.canonical_id, body.share_numbers)


@router.delete("/{club_id}/sessions/{session_id}/participation")
def unlink_workout(club_id: str, session_id: int, db: Session = Depends(get_db)):
    return _call(team.unlink_workout, db, club_id, session_id)


@router.get("/{club_id}/summary")
def summary(club_id: str, start: Optional[date] = None, end: Optional[date] = None, db: Session = Depends(get_db)):
    return _call(team.team_summary, db, club_id, start, end)


# ---------------------------------------------------------------- challenges

@router.get("/{club_id}/challenges")
def list_challenges(club_id: str, db: Session = Depends(get_db)):
    return {"challenges": _call(challenges.list_challenges, db, club_id)}


@router.post("/{club_id}/challenges")
def create_challenge(club_id: str, body: ChallengeBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(challenges.create_challenge, db, club_id, **body.model_dump())


@router.get("/{club_id}/challenges/{challenge_id}")
def get_challenge(club_id: str, challenge_id: int, db: Session = Depends(get_db)):
    return _call(challenges.get_challenge, db, club_id, challenge_id)


@router.post("/{club_id}/challenges/{challenge_id}/join")
def join_challenge(club_id: str, challenge_id: int, db: Session = Depends(get_db)):
    _throttle()
    return _call(challenges.join_challenge, db, club_id, challenge_id)


@router.post("/{club_id}/challenges/{challenge_id}/leave")
def leave_challenge(club_id: str, challenge_id: int, db: Session = Depends(get_db)):
    return _call(challenges.leave_challenge, db, club_id, challenge_id)


@router.post("/{club_id}/challenges/{challenge_id}/excuse")
def excuse_week(club_id: str, challenge_id: int, body: ExcuseBody, db: Session = Depends(get_db)):
    return _call(challenges.excuse_week, db, club_id, challenge_id, body.week, body.excused)


# ---------------------------------------------------------------- results and the club board

@router.get("/{club_id}/leaderboard")
def leaderboard(club_id: str, board: str = "2000m", db: Session = Depends(get_db)):
    return _call(team.club_leaderboard, db, club_id, board)


@router.post("/{club_id}/results")
def share_result(club_id: str, body: ResultBody, db: Session = Depends(get_db)):
    _throttle()
    return _call(team.share_result, db, club_id, body.ref, body.note)


@router.delete("/{club_id}/results/{result_id}")
def withdraw_result(club_id: str, result_id: int, db: Session = Depends(get_db)):
    return _call(team.withdraw_result, db, club_id, result_id)


@router.post("/{club_id}/results/{result_id}/hide")
def hide_result(club_id: str, result_id: int, body: ReasonBody, db: Session = Depends(get_db)):
    return _call(team.hide_result, db, club_id, result_id, body.reason)


# ---------------------------------------------------------------- safety

@router.post("/{club_id}/report")
def report(club_id: str, body: ReportBody, db: Session = Depends(get_db)):
    _throttle("report")
    return _call(svc.report, db, club_id, body.target_type, body.target_id, body.reason, body.detail)


@router.post("/{club_id}/blocks/{ref}")
def block(club_id: str, ref: str, db: Session = Depends(get_db)):
    return _call(svc.block, db, club_id, ref)


@router.delete("/{club_id}/blocks/{ref}")
def unblock(club_id: str, ref: str, db: Session = Depends(get_db)):
    return _call(svc.unblock, db, club_id, ref)


@router.get("/{club_id}/audit")
def audit_log(club_id: str, db: Session = Depends(get_db)):
    return {"events": _call(svc.audit_log, db, club_id)}


# ---------------------------------------------------------------- logo (fetched with the bearer header and shown from a blob: an <img src> can't send it)

@router.get("/{club_id}/logo")
def get_logo(club_id: str, db: Session = Depends(get_db)):
    content_type, data = _call(svc.get_logo, db, club_id)
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.put("/{club_id}/logo")
async def put_logo(club_id: str, request: Request, db: Session = Depends(get_db)):
    _throttle()
    data = await request.body()
    return _call(svc.put_logo, db, club_id, (request.headers.get("content-type") or "").split(";")[0].strip(), data)


@router.delete("/{club_id}/logo")
def delete_logo(club_id: str, db: Session = Depends(get_db)):
    return _call(svc.delete_logo, db, club_id)
