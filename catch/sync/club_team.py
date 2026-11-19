"""Clubs (session 27; docs/clubs.md §6): announcements, team sessions and the club calendar, participation, summaries, shared results.

A team session is a plan for the club. It is never a completed workout and never a PlannedWorkout (no per-person plan is created), and a
member's completed workout is never copied into the club: they may *associate* one with a session, and what that stores is the fact they
took part plus, only if they chose, the distance and time. Recovery, sleep, weight and nutrition are not columns anywhere in these tables."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from catch.analytics import clubs as c
from catch.analytics import leaderboards as lb
from catch.core.models import (
    CanonicalActivity, ClubAnnouncement, ClubChallenge, ClubMember, ClubMemberPrefs, ClubResult, ClubSession, ClubSessionParticipation,
)
from catch.sync import clubs as svc
from catch.sync import leaderboard_store as lb_store
from catch.sync.clubs import ClubError, _aware, _value, audit, me, member_ref, require_member

_KINDS = {"announcement": ClubAnnouncement, "session": ClubSession, "challenge": ClubChallenge}
SESSIONS_PER_DAY = 10  # a club can't spam its calendar
POSTS_PER_DAY = 10


def _overrides(a: CanonicalActivity) -> dict:
    import json

    try:
        return json.loads(a.overrides_json or "{}")
    except ValueError:
        return {}


# ---------------------------------------------------------------- announcements, and the approval every junior-club post goes through

def _post_status(role: str, audience: str) -> str:
    return c.post_status_for(role, audience)


def _author_label(handles: dict, owner_id: Optional[str]) -> str:
    p = handles.get(owner_id) if owner_id else None
    return p.handle if p else "a former member"


def post_announcement(session: Session, club_id: str, title: str, body: str) -> dict:
    from catch.sync.clubs import _not_restricted

    _not_restricted("posting")
    club, m = require_member(session, club_id, "post")
    title, body = _value(c.validate_post, title, body, club.audience)
    since = datetime.now(timezone.utc) - timedelta(days=1)
    if session.exec(select(func.count()).select_from(ClubAnnouncement).where(ClubAnnouncement.club_id == club_id, ClubAnnouncement.created_at > since)).one() >= POSTS_PER_DAY:
        raise ClubError("This club has posted a lot today. Try again tomorrow.", 429)
    status = _post_status(m.role, club.audience)
    post = ClubAnnouncement(club_id=club_id, author_id=me(), title=title, body=body, status=status)
    session.add(post)
    session.flush()
    audit(session, club_id, "post_created", "published" if status == "published" else "held for a coach's approval", kind="staff", target_type="announcement", target_id=str(post.id))
    session.commit()
    return {"id": post.id, "status": status, "message": None if status == "published" else "In a junior club a coach approves a post before members see it."}


def announcements(session: Session, club_id: str, limit: int = 30) -> list[dict]:
    club, m = require_member(session, club_id)
    staff = c.can(m.role, "post")
    stmt = select(ClubAnnouncement).where(ClubAnnouncement.club_id == club_id)
    if not staff:
        stmt = stmt.where(ClubAnnouncement.status == "published")
    rows = session.exec(stmt.order_by(ClubAnnouncement.id.desc()).limit(max(1, min(limit, 100)))).all()  # type: ignore[attr-defined]
    people = svc.handles(session, {r.author_id for r in rows if r.author_id})
    return [{"id": r.id, "title": r.title, "body": r.body, "status": r.status, "author": _author_label(people, r.author_id), "created_at": _aware(r.created_at).isoformat(),
             "can_approve": r.status == "pending" and c.may_approve_post(m.role, club.audience), "decision_reason": r.decision_reason if staff else None}
            for r in rows if staff or r.status == "published"]


def decide_post(session: Session, club_id: str, kind: str, post_id: int, action: str, reason: Optional[str] = None) -> dict:
    """approve (needs the right to publish here), reject (a pending post), or take down (any staff). Every decision is audited with its reason."""
    club, m = require_member(session, club_id, "take_down_post")
    model = _KINDS.get(kind)
    if model is None or action not in ("approve", "reject", "hide"):
        raise ClubError("Choose a post and an action.")
    post = session.get(model, post_id)
    if post is None or post.club_id != club_id:
        raise ClubError("Not found.", 404)
    live = {"announcement": "published", "session": "published", "challenge": "active"}[kind]
    down = {"announcement": "hidden", "session": "cancelled", "challenge": "cancelled"}[kind]
    if action == "approve":
        if post.status != "pending":
            raise ClubError("That isn't waiting for approval.", 409)
        if not c.may_approve_post(m.role, club.audience):
            raise ClubError("In a junior club only a coach or the owner approves a post.", 403)
        post.status, post.decided_by = live, me()
    elif action == "reject":
        if post.status != "pending":
            raise ClubError("That isn't waiting for approval.", 409)
        post.status, post.decided_by, post.decision_reason = "rejected", me(), _value(c.validate_reason, reason)
    else:
        if post.status not in (live, "pending"):
            raise ClubError("That is already down.", 409)
        post.status, post.decided_by, post.decision_reason = down, me(), _value(c.validate_reason, reason)
    if hasattr(post, "decided_at"):
        post.decided_at = datetime.now(timezone.utc)
    session.add(post)
    audit(session, club_id, f"{kind}_{'approved' if action == 'approve' else action + 'ed' if action == 'reject' else 'taken_down'}", (reason or "approved").strip(), kind="staff",
          target_type=kind, target_id=str(post_id))
    session.commit()
    return {"id": post_id, "status": post.status}


# ---------------------------------------------------------------- team sessions and the calendar

def create_session(session: Session, club_id: str, *, title: str, session_type: str, on: date, start_time: Optional[str] = None, duration_min: Optional[int] = None,
                   distance_m: Optional[int] = None, description: Optional[str] = None) -> dict:
    club, m = require_member(session, club_id, "post")
    title = _value(c.validate_post, title, "x", club.audience)[0]
    description = _value(c.validate_post, title, description, club.audience)[1] if (description or "").strip() else None
    if session_type not in c.SESSION_TYPES:
        raise ClubError("Choose a session type from the list.")
    if start_time and not (len(start_time) == 5 and start_time[2] == ":" and start_time[:2].isdigit() and start_time[3:].isdigit() and int(start_time[:2]) < 24 and int(start_time[3:]) < 60):
        raise ClubError("Start time looks like 06:30.")
    if duration_min is not None and not (1 <= duration_min <= 600) or distance_m is not None and not (1 <= distance_m <= 100000):
        raise ClubError("Duration is 1-600 minutes and distance 1-100,000 m.")
    if abs((on - date.today()).days) > 400:
        raise ClubError("Choose a date within the next year.")
    status = _post_status(m.role, club.audience)
    row = ClubSession(club_id=club_id, created_by=me(), title=title, session_type=session_type, date=on, start_time=start_time or None, duration_min=duration_min,
                      distance_m=distance_m, description=description, status=status)
    session.add(row)
    session.flush()
    audit(session, club_id, "session_created", "published" if status == "published" else "held for a coach's approval", kind="staff", target_type="session", target_id=str(row.id))
    session.commit()
    return {"id": row.id, "status": status, "message": None if status == "published" else "In a junior club a coach approves a session before members see it."}


def _participation_counts(session: Session, club_id: str) -> dict[int, int]:
    return {sid: n for sid, n in session.exec(select(ClubSessionParticipation.session_id, func.count()).where(ClubSessionParticipation.club_id == club_id)
                                              .group_by(ClubSessionParticipation.session_id)).all()}  # type: ignore[arg-type]


def calendar(session: Session, club_id: str, start: Optional[date] = None, end: Optional[date] = None) -> dict:
    club, m = require_member(session, club_id)
    start = start or date.today() - timedelta(days=7)
    end = end or start + timedelta(days=60)
    if (end - start).days > 400:
        raise ClubError("Ask for at most a year at a time.")
    staff = c.can(m.role, "post")
    stmt = select(ClubSession).where(ClubSession.club_id == club_id, ClubSession.date >= start, ClubSession.date <= end)
    if not staff:
        stmt = stmt.where(ClubSession.status == "published")
    rows = session.exec(stmt.order_by(ClubSession.date, ClubSession.start_time).limit(500)).all()  # type: ignore[arg-type]
    counts = _participation_counts(session, club_id)
    mine = {p.session_id: p for p in session.exec(select(ClubSessionParticipation).where(ClubSessionParticipation.club_id == club_id, ClubSessionParticipation.owner_id == me())).all()}
    return {"sessions": [{
        "id": r.id, "title": r.title, "type": r.session_type, "date": r.date.isoformat(), "start_time": r.start_time, "duration_min": r.duration_min, "distance_m": r.distance_m,
        "description": r.description, "status": r.status, "participants": counts.get(r.id, 0), "i_took_part": r.id in mine,
        "can_approve": r.status == "pending" and c.may_approve_post(m.role, club.audience),
    } for r in rows if staff or r.status == "published"], "from": start.isoformat(), "to": end.isoformat()}


def link_workout(session: Session, club_id: str, session_id: int, canonical_id: int, share_numbers: Optional[bool] = None) -> dict:
    """The member chooses to say 'this workout was that session'. Only the fact, and (if they choose) distance and time, are stored."""
    club, m = require_member(session, club_id, "link_workout")
    cs = session.get(ClubSession, session_id)
    if cs is None or cs.club_id != club_id or cs.status != "published":
        raise ClubError("Not found.", 404)
    workout = session.get(CanonicalActivity, canonical_id)  # owner-scoped: someone else's workout is simply not found
    if workout is None or workout.start is None or _overrides(workout).get("exclude_from_totals"):
        raise ClubError("Not found.", 404)
    if abs((workout.start.astimezone().date() - cs.date).days) > 1:
        raise ClubError("That workout isn't on this session's day.")
    prefs = session.get(ClubMemberPrefs, (club_id, me()))
    share = bool(prefs and prefs.share_numbers) if share_numbers is None else bool(share_numbers)
    row = session.get(ClubSessionParticipation, (session_id, me())) or ClubSessionParticipation(session_id=session_id, owner_id=me(), club_id=club_id)
    row.shared_distance_m = int(workout.distance) if share and workout.distance else None
    row.shared_duration_s = int(workout.duration) if share and workout.duration else None
    session.add(row)
    session.commit()
    return {"took_part": True, "shared_numbers": share and (row.shared_distance_m is not None or row.shared_duration_s is not None)}


def unlink_workout(session: Session, club_id: str, session_id: int) -> dict:
    require_member(session, club_id, "link_workout")
    row = session.get(ClubSessionParticipation, (session_id, me()))
    if row is not None:
        session.delete(row)
        session.commit()
    return {"took_part": False}


def team_summary(session: Session, club_id: str, start: Optional[date] = None, end: Optional[date] = None) -> dict:
    """Aggregates only: counts, and totals that appear only when at least three members chose to share a number. No person is ever a row."""
    club, m = require_member(session, club_id)
    end = end or date.today()
    start = start or end - timedelta(days=90)
    sessions = session.exec(select(ClubSession).where(ClubSession.club_id == club_id, ClubSession.status == "published", ClubSession.date >= start, ClubSession.date <= end)).all()
    ids = [s.id for s in sessions]
    rows = session.exec(select(ClubSessionParticipation).where(ClubSessionParticipation.club_id == club_id, ClubSessionParticipation.session_id.in_(ids))).all() if ids else []  # type: ignore[attr-defined]
    active = session.exec(select(func.count()).select_from(ClubMember).where(ClubMember.club_id == club_id, ClubMember.status == "active")).one()
    anonymous = [{"session_id": r.session_id, "shared_distance_m": r.shared_distance_m, "shared_duration_s": r.shared_duration_s} for r in rows]  # identities dropped here
    return {**c.team_summary([{"id": s.id, "title": s.title, "date": s.date.isoformat()} for s in sessions], anonymous, active), "from": start.isoformat(), "to": end.isoformat()}


# ---------------------------------------------------------------- shared results and the club leaderboard

def share_result(session: Session, club_id: str, ref: dict, note: Optional[str] = None) -> dict:
    """Explicitly share one exact-distance/time result with this club. Built from the leaderboards' own eligibility and verification, so a club
    board can never rank something the public boards wouldn't, and 'verified' means exactly what it means there."""
    club, m = require_member(session, club_id, "share_result")
    from catch.sync import leaderboards as lbsvc

    try:
        r = lbsvc._result_from_ref(session, ref)
        verification = lbsvc._verification_for(session, r)
    except lbsvc.LeaderboardError as exc:
        raise ClubError(str(exc), exc.status) from None
    if r["elig"] is None:
        raise ClubError("Only an exact 500 m, 1,000 m, 2,000 m, 5,000 m, 6,000 m, 30-minute or 60-minute result can be shared to a board.")
    board_key, value = r["elig"]
    note_v = _value(lb.validate_note, note)
    import hashlib
    import hmac

    source_key = hmac.new(svc._secret().encode(), f"result:{club_id}:{r['kind']}:{r['result_id']}".encode(), hashlib.sha256).hexdigest()[:32]
    row = ClubResult(club_id=club_id, owner_id=me(), board_key=board_key, value=value, verification=verification, source_key=source_key, note=note_v)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ClubError("You've already shared this result with this club.", 409) from None
    return {"shared": True, "id": row.id, "board_key": board_key, "verification": verification}


def withdraw_result(session: Session, club_id: str, result_id: int) -> dict:
    require_member(session, club_id, "share_result")
    row = session.get(ClubResult, result_id)
    if row is None or row.club_id != club_id or row.owner_id != me():
        raise ClubError("Not found.", 404)
    session.delete(row)
    session.commit()
    return {"withdrawn": True}


def hide_result(session: Session, club_id: str, result_id: int, reason: str) -> dict:
    club, _ = require_member(session, club_id, "hide_result")
    row = session.get(ClubResult, result_id)
    if row is None or row.club_id != club_id:
        raise ClubError("Not found.", 404)
    reason = _value(c.validate_reason, reason)
    row.status = "hidden"
    session.add(row)
    audit(session, club_id, "result_hidden", reason, kind="staff", target_type="result", target_id=str(result_id), subject=row.owner_id)
    session.commit()
    return {"hidden": True}


def club_leaderboard(session: Session, club_id: str, board_key: str) -> dict:
    """Members' explicitly shared results, plus (for a member who ticked 'also show my public results here') their existing public entries.
    Only verified results are ranked; the rest follow, labelled, in their own list — the same rule as the public boards."""
    club, m = require_member(session, club_id)
    if board_key not in lb.BOARDS:
        raise ClubError("Not found.", 404)
    active = {x.owner_id: x for x in session.exec(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.status == "active")).all()}
    blocked = svc.my_blocks(session)
    rows: list[dict] = []
    for r in session.exec(select(ClubResult).where(ClubResult.club_id == club_id, ClubResult.board_key == board_key, ClubResult.status == "active")).all():
        if r.owner_id in active and r.owner_id not in blocked:
            rows.append({"entry_id": f"club:{r.id}", "owner_id": r.owner_id, "value": r.value, "verification": r.verification, "athlete_key": r.owner_id, "public_id": r.owner_id,
                         "tiebreak": lb.tiebreak_for(f"club:{r.id}"), "source": "club", "id": r.id})
    if club.audience == "adult":
        show = {p.owner_id for p in session.exec(select(ClubMemberPrefs).where(ClubMemberPrefs.club_id == club_id, ClubMemberPrefs.include_public_results == True)).all()}  # noqa: E712
        for e in lb_store.public_entries_for_owners(board_key, [o for o in show if o in active and o not in blocked]):
            rows.append({"entry_id": e["entry_id"], "owner_id": e["owner_id"], "value": e["value"], "verification": e["verification"], "athlete_key": e["owner_id"], "public_id": e["owner_id"],
                         "tiebreak": e["tiebreak"], "source": "public", "id": None})
    ranked = lb.rank_board(rows, board_key, include_unverified=True)
    people = svc.handles(session, {r["owner_id"] for r in rows})

    def shape(r: dict) -> dict:
        p = people.get(r["owner_id"])
        return {"rank": r["rank"], "name": p.handle if p else "Member", **lb.format_value(board_key, r["value"]), "verification": r["verification"],
                "verification_label": lb.VERIFICATION_LABELS[r["verification"]], "source": r["source"], "is_me": r["owner_id"] == me(),
                "result_id": r["id"] if r["owner_id"] == me() else None, "member_ref": member_ref(club_id, r["owner_id"])}

    return {"board_key": board_key, "board_label": lb.BOARDS[board_key]["label"], "ranked": [shape(r) for r in ranked["ranked"]], "unverified": [shape(r) for r in ranked["unverified"]],
            "note": "Only verified results are ranked. Equal results share a rank. Members choose what they share here; nothing else about them is shown."}
