"""Clubs (session 27; docs/clubs.md §7): group challenges. The DB half; the rules are catch/analytics/challenges.py.

A member's standing is computed HERE, as them, from their own activities (which no other member can read) and written to
`club_challenge_entries` as a single integer. Other members see that integer and the member's handle, never an activity. The browser can't
post a score: no endpoint accepts one.

What counts: activities recorded by a connected source (Garmin, Concept2, Whoop) — a Concept2 result must also carry Concept2's own `verified` flag. Typed-in work in Catch (the in-app strength logger, pieces) never counts,
and neither does anything the member excluded from their totals. Sport comes from the provider's own record, not a label the member can edit. One real
activity can count for one account: `club_challenge_claims` (a keyed hash, global primary key) makes a second account's claim on it fail, and that
account's score is recomputed without it."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from catch.analytics import challenges as ch
from catch.analytics import verification as vf
from catch.analytics import clubs as c
from catch.analytics import leaderboards as lb
from catch.core.models import Activity, CanonicalActivity, ClubChallenge, ClubChallengeClaim, ClubChallengeEntry, ClubMember
from catch.sync import clubs as svc
from catch.sync.clubs import ClubError, _value, audit, me, member_ref, require_member
from catch.sync.tracks import family_of

PROVIDERS = ("garmin", "concept2", "whoop")  # catch_strength is typed in by the member, so it is never a source
_PREFERRED = {"concept2": 0, "garmin": 1, "whoop": 2}  # the key follows the identity two accounts could share (a Concept2 login)
CHALLENGES_PER_DAY = 5


def spec_of(row: ClubChallenge, audience: str) -> ch.ChallengeSpec:
    return ch.ChallengeSpec(row.metric, row.start_date, row.end_date, row.goal, audience, row.sport, row.target_per_week, row.day_cap_m, row.day_cap_s, row.min_session_s)


def _local_day_bounds(d: date) -> tuple[datetime, datetime]:
    from catch.sync.training_intelligence import _local_day_utc_range

    return _local_day_utc_range(d)


def member_activities(session: Session, spec: ch.ChallengeSpec) -> list[dict]:
    """The caller's own activities in the window, reduced to the only fields scoring may see. No health value is read: not heart rate, not
    wellness, not body composition."""
    lo, _ = _local_day_bounds(spec.start)
    _, hi = _local_day_bounds(spec.end)
    canon = session.exec(select(CanonicalActivity).where(CanonicalActivity.start >= lo, CanonicalActivity.start < hi)).all()
    if not canon:
        return []
    members: dict[int, list[Activity]] = {}
    for a in session.exec(select(Activity).where(Activity.canonical_id.in_([k.id for k in canon]))).all():  # type: ignore[attr-defined]
        members.setdefault(a.canonical_id, []).append(a)
    secret = svc._secret()
    out = []
    for k in canon:
        # A Concept2 result must carry Concept2's own `verified` flag (what separates a PM5/ErgData result from one typed into the logbook by hand).
        # Garmin and Whoop don't tell Catch whether a workout was entered by hand, so a manual entry there can't be detected (docs/clubs.md §5, §14).
        provider = sorted([a for a in members.get(k.id, []) if a.source in PROVIDERS and (a.source != "concept2" or vf.concept2_meta(a)["verified"] is True)],
                          key=lambda a: (_PREFERRED[a.source], str(a.external_id)))
        first = provider[0] if provider else None
        board = None
        for a in provider:
            if a.source == "concept2":
                has_intervals = bool(a.intervals_json and '"intervals"' in a.intervals_json)
                elig = lb.eligible_board(distance_m=a.distance, duration_s=a.duration, workout_type=a.workout_type, erg_type=a.type, has_intervals=has_intervals)
                board = elig[0] if elig else None
        try:
            excluded = bool(json.loads(k.overrides_json or "{}").get("exclude_from_totals"))
        except ValueError:
            excluded = False
        out.append({
            "key": ch.activity_key(secret, first.source, str(first.external_id)) if first else f"typed-{k.id}", "date": k.start.astimezone().date(), "start": k.start,
            "duration_s": k.duration, "distance_m": k.distance, "sport_family": family_of(first) if first else None, "provider_sourced": first is not None,
            "excluded": excluded, "absorbed": k.absorbed_into_piece_id is not None, "board_key": board,
        })
    return out


def _excused(entry: ClubChallengeEntry) -> list[date]:
    return [date.fromisoformat(x) for x in (entry.excused_weeks or "").split(",") if x]


def refresh_entry(session: Session, row: ClubChallenge, entry: ClubChallengeEntry, audience: str, *, today: Optional[date] = None) -> ch.Score:
    """Recompute this member's standing and claim the activities it relied on; an activity another account already holds is dropped and
    the score recomputed without it."""
    today = today or date.today()
    spec = spec_of(row, audience)
    acts = member_activities(session, spec)
    mine = {cl.activity_key for cl in session.exec(select(ClubChallengeClaim).where(ClubChallengeClaim.challenge_id == row.id, ClubChallengeClaim.owner_id == me())).all()}  # explicit: correctness must not depend on RLS hiding others' claims
    lost: set[str] = set()
    result = ch.score(spec, acts, as_of=today, excused_weeks=_excused(entry))
    for _ in range(4):
        wanted = set(result.claimed_keys) - mine
        newly_lost = set()
        for key in wanted:
            try:
                with session.begin_nested():
                    session.add(ClubChallengeClaim(challenge_id=row.id, activity_key=key, owner_id=me()))
                    session.flush()
                mine.add(key)
            except IntegrityError:
                newly_lost.add(key)
        if not newly_lost:
            break
        lost |= newly_lost
        result = ch.score(spec, [a for a in acts if a["key"] not in lost], as_of=today, excused_weeks=_excused(entry))
    for key in mine - set(result.claimed_keys):
        stale = session.get(ClubChallengeClaim, (row.id, key))
        if stale is not None and ch.phase(spec, today) != "closed":
            session.delete(stale)
    entry.value, entry.updated_at = result.value, datetime.now(timezone.utc)
    session.add(entry)
    return result


def refresh_my_scores(session: Session) -> int:
    """After a sync, or when someone looks: every challenge this person is in that hasn't frozen. Only ever the caller's own entries."""
    today, n = date.today(), 0
    entries = session.exec(select(ClubChallengeEntry).where(ClubChallengeEntry.owner_id == me(), ClubChallengeEntry.status == "joined")).all()
    for entry in entries:
        row = session.get(ClubChallenge, entry.challenge_id)
        mem = session.get(ClubMember, (entry.club_id, me()))
        if row is None or row.status != "active" or mem is None or mem.status != "active":
            continue
        if ch.phase(spec_of(row, mem.club_audience), today) == "closed":
            continue
        refresh_entry(session, row, entry, mem.club_audience, today=today)
        n += 1
    if n:
        session.commit()
    return n


# ---------------------------------------------------------------- create, list, show

def create_challenge(session: Session, club_id: str, *, title: str, metric: str, start: date, end: date, goal: Optional[int] = None, description: Optional[str] = None,
                     sport: str = "rowing", target_per_week: Optional[int] = None, day_cap_m: Optional[int] = None, day_cap_s: Optional[int] = None,
                     min_session_s: Optional[int] = None) -> dict:
    club, m = require_member(session, club_id, "post")
    title_v = _value(c.validate_post, title, "x", club.audience)[0]
    desc = _value(c.validate_post, title, description, club.audience)[1] if (description or "").strip() else None
    spec = _value(ch.validate_challenge, metric=metric, start=start, end=end, goal=goal, audience=club.audience, sport=sport, target_per_week=target_per_week,
                  day_cap_m=day_cap_m, day_cap_s=day_cap_s, min_session_s=min_session_s, today=date.today())
    made = session.exec(select(func.count()).select_from(ClubChallenge).where(ClubChallenge.club_id == club_id, ClubChallenge.start_date >= date.today() - timedelta(days=1),
                                                                               ClubChallenge.status.in_(["pending", "active"]))).one()  # type: ignore[attr-defined]
    if made >= CHALLENGES_PER_DAY * 4:
        raise ClubError("This club has a lot of challenges running. Let some finish first.", 429)
    status = c.post_status_for(m.role, club.audience)
    row = ClubChallenge(club_id=club_id, created_by=me(), title=title_v, description=desc, metric=spec.metric, sport=spec.sport, start_date=spec.start, end_date=spec.end, goal=spec.goal,
                        target_per_week=spec.target_per_week, day_cap_m=spec.day_cap_m, day_cap_s=spec.day_cap_s, min_session_s=spec.min_session_s,
                        status="active" if status == "published" else "pending")
    session.add(row)
    session.flush()
    audit(session, club_id, "challenge_created", "published" if status == "published" else "held for a coach's approval", kind="staff", target_type="challenge", target_id=str(row.id))
    session.commit()
    return {"id": row.id, "status": row.status, "rules": ch.describe(spec), "message": None if row.status == "active" else "In a junior club a coach approves a challenge before members see it."}


def _my_entry(session: Session, challenge_id: int) -> Optional[ClubChallengeEntry]:
    return session.get(ClubChallengeEntry, (challenge_id, me()))


def _row_dict(session: Session, club, mem: ClubMember, row: ClubChallenge, counts: dict[int, int]) -> dict:
    spec = spec_of(row, club.audience)
    entry = _my_entry(session, row.id)
    today = date.today()
    return {
        "id": row.id, "title": row.title, "description": row.description, "metric": row.metric, "sport": row.sport, "start": row.start_date.isoformat(), "end": row.end_date.isoformat(),
        "goal": row.goal, "status": row.status, "phase": ch.phase(spec, today) if row.status == "active" else row.status, "participants": counts.get(row.id, 0),
        "joined": bool(entry and entry.status == "joined"), "my_value": ch.format_value(spec, entry.value) if entry and entry.status == "joined" else None,
        "can_join": row.status == "active" and ch.can_join(spec, today) and not (entry and entry.status == "joined"),
        "can_approve": row.status == "pending" and c.may_approve_post(mem.role, club.audience),
    }


def list_challenges(session: Session, club_id: str) -> list[dict]:
    club, m = require_member(session, club_id)
    staff = c.can(m.role, "post")
    stmt = select(ClubChallenge).where(ClubChallenge.club_id == club_id)
    if not staff:
        stmt = stmt.where(ClubChallenge.status == "active")
    rows = session.exec(stmt.order_by(ClubChallenge.start_date.desc()).limit(100)).all()  # type: ignore[attr-defined]
    counts = {i: n for i, n in session.exec(select(ClubChallengeEntry.challenge_id, func.count()).where(ClubChallengeEntry.club_id == club_id, ClubChallengeEntry.status == "joined")
                                            .group_by(ClubChallengeEntry.challenge_id)).all()}  # type: ignore[arg-type]
    return [_row_dict(session, club, m, r, counts) for r in rows if staff or r.status == "active"]


def standings(session: Session, club, row: ClubChallenge) -> list[dict]:
    spec = spec_of(row, club.audience)
    active = {x.owner_id for x in session.exec(select(ClubMember).where(ClubMember.club_id == club.club_id, ClubMember.status == "active")).all()}
    entries = [e for e in session.exec(select(ClubChallengeEntry).where(ClubChallengeEntry.challenge_id == row.id, ClubChallengeEntry.status == "joined")).all() if e.owner_id in active]
    blocked = svc.my_blocks(session)
    people = svc.handles(session, {e.owner_id for e in entries})
    ranked = ch.rank_standings([{"owner_id": e.owner_id, "value": e.value} for e in entries if e.owner_id not in blocked], row.id)
    return [{"rank": r["rank"], "name": people[r["owner_id"]].handle if r["owner_id"] in people else "Member", "value": ch.format_value(spec, r["value"]), "raw": r["value"],
             "is_me": r["owner_id"] == me(), "member_ref": member_ref(club.club_id, r["owner_id"])} for r in ranked]


def get_challenge(session: Session, club_id: str, challenge_id: int) -> dict:
    club, m = require_member(session, club_id)
    row = session.get(ClubChallenge, challenge_id)
    if row is None or row.club_id != club_id or (row.status != "active" and not c.can(m.role, "post")):
        raise ClubError("Not found.", 404)
    spec = spec_of(row, club.audience)
    entry = _my_entry(session, challenge_id)
    detail = None
    if entry and entry.status == "joined" and row.status == "active" and ch.phase(spec, date.today()) != "closed":
        detail = refresh_entry(session, row, entry, club.audience).detail
        session.commit()
    elif entry and entry.status == "joined" and row.status == "active":
        detail = ch.score(spec, member_activities(session, spec), as_of=date.today(), excused_weeks=_excused(entry)).detail  # frozen: shown, never rewritten
    counts = {challenge_id: sum(1 for _ in standings(session, club, row))}
    head = _row_dict(session, club, m, row, counts)
    if detail is not None and entry is not None:
        head["my_value"] = ch.format_value(spec, entry.value, detail)  # "3 of 4 weeks" reads better than a percentage once the weeks are known
    return {**head, "rules": ch.describe(spec), "standings": standings(session, club, row) if row.status == "active" else [], "my_detail": detail,
            "excused_weeks": [d.isoformat() for d in _excused(entry)] if entry else [], "settles_on": (row.end_date + timedelta(days=ch.GRACE_DAYS)).isoformat(),
            "target_per_week": row.target_per_week, "min_session_minutes": row.min_session_s // 60}


# ---------------------------------------------------------------- joining, leaving, excusing a week

def join_challenge(session: Session, club_id: str, challenge_id: int) -> dict:
    club, m = require_member(session, club_id, "join_challenge")
    row = session.get(ClubChallenge, challenge_id)
    if row is None or row.club_id != club_id or row.status != "active":
        raise ClubError("Not found.", 404)
    spec = spec_of(row, club.audience)
    if not ch.can_join(spec, date.today()):
        raise ClubError("This challenge has ended.", 409)
    entry = _my_entry(session, challenge_id) or ClubChallengeEntry(challenge_id=challenge_id, owner_id=me(), club_id=club_id)
    entry.status = "joined"
    session.add(entry)
    session.flush()
    refresh_entry(session, row, entry, club.audience)
    session.commit()
    return {"joined": True, "value": ch.format_value(spec, entry.value)}


def leave_challenge(session: Session, club_id: str, challenge_id: int) -> dict:
    """Opting out is always allowed while the challenge is open: the member leaves the standings and their claims are released."""
    require_member(session, club_id, "join_challenge")
    entry = _my_entry(session, challenge_id)
    if entry is None or entry.club_id != club_id:
        raise ClubError("Not found.", 404)
    entry.status, entry.value = "left", 0
    session.add(entry)
    for cl in session.exec(select(ClubChallengeClaim).where(ClubChallengeClaim.challenge_id == challenge_id, ClubChallengeClaim.owner_id == me())).all():
        session.delete(cl)
    session.commit()
    return {"joined": False}


def excuse_week(session: Session, club_id: str, challenge_id: int, week: date, excused: bool = True) -> dict:
    """Excusing a week (illness, rest, travel) is a plain switch with no reason stored, and an excused week is not counted against the member."""
    club, m = require_member(session, club_id, "join_challenge")
    row = session.get(ClubChallenge, challenge_id)
    entry = _my_entry(session, challenge_id)
    if row is None or row.club_id != club_id or entry is None or entry.status != "joined":
        raise ClubError("Not found.", 404)
    if row.metric != "consistency":
        raise ClubError("Only a consistency challenge has weeks to excuse.")
    monday = ch.monday(week)
    if monday not in ch.week_starts(row.start_date, row.end_date):
        raise ClubError("That week isn't part of this challenge.")
    if ch.phase(spec_of(row, club.audience), date.today()) == "closed":
        raise ClubError("This challenge has settled.", 409)
    weeks = {d for d in _excused(entry)}
    (weeks.add if excused else weeks.discard)(monday)
    entry.excused_weeks = ",".join(sorted(d.isoformat() for d in weeks)) or None
    session.add(entry)
    refresh_entry(session, row, entry, club.audience)
    session.commit()
    return {"excused_weeks": sorted(d.isoformat() for d in weeks), "value": ch.format_value(spec_of(row, club.audience), entry.value)}

