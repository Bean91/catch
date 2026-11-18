from __future__ import annotations

"""Session 27 (docs/clubs.md §11): five READ-ONLY club tools, merged into catch.coach.tools.TOOLS.

They call the same service functions the REST routes call (catch/sync/clubs.py, club_team.py, club_challenges.py) as the signed-in owner,
so a club's role and membership rules — and, on Postgres, its row-level security — apply to an assistant exactly as they do to the person: a
tool can read only what that person could read in the app, and there is no argument that names another user. They return what a member sees:
handles, roles, published posts, counts, ranked standings; never recovery, sleep, weight, nutrition or anyone's training.

There are deliberately NO club write tools. Creating a club, inviting, approving a request, removing a member, publishing a post or a
challenge and moderating are decisions with consequences for other people (some of them young), so they are the person's own act in the app,
with its confirmations and audit trail, not something an assistant or an MCP client does for them (same stance as session 26's leaderboard
tools). A coach-role device token reaches none of these tools: they are athlete-only."""

from datetime import date
from typing import Optional

from sqlmodel import Session

from catch.analytics import leaderboards as lb
from catch.core import principal as pr
from catch.core.principal import principal_from
from catch.sync import club_challenges as challenges
from catch.sync import club_team as team
from catch.sync import clubs as svc

_UNAVAILABLE = {"available": False, "reason": "Clubs exist only on the public deployment."}


def _athlete(ctx: dict) -> None:
    if principal_from(ctx).role != pr.ATHLETE_ROLE:
        raise ValueError("Only the athlete's own session can use the club tools.")


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.ClubError as exc:
        raise ValueError(str(exc)) from None


def _day(raw: Optional[str], name: str) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"{name} must be a date like 2026-11-30") from None


def _get_my_clubs(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx)
    if not svc.available():
        return _UNAVAILABLE
    data = _wrap(svc.my_clubs, session)
    keep = ("club_id", "name", "audience", "visibility", "my_role", "member_count", "status", "pending")
    return {"available": True, "has_club_profile": data["profile"]["exists"], "clubs": [{k: c.get(k) for k in keep} for c in data["clubs"]],
            "waiting_requests": [{"club_name": r["club_name"], "status": r["status"]} for r in data["requests"] if r["status"] == "pending"]}


def _get_club(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx)
    if not svc.available():
        return _UNAVAILABLE
    club_id = args.get("club_id")
    if not club_id:
        raise ValueError("club_id is required (get_my_clubs lists them)")
    club = _wrap(svc.get_club, session, club_id)
    out = {"available": True, "club": {k: club.get(k) for k in ("club_id", "name", "description", "location", "visibility", "audience", "join_policy", "rules", "status", "member_count", "my_role")}}
    if club.get("my_role"):
        out["members"] = [{"handle": m["handle"], "role": m["role"]} for m in _wrap(svc.members, session, club_id)["members"]]
        out["announcements"] = [{"title": a["title"], "body": a["body"], "author": a["author"], "status": a["status"], "created_at": a["created_at"]}
                                for a in _wrap(team.announcements, session, club_id, 10)]
    return out


def _get_club_calendar(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx)
    if not svc.available():
        return _UNAVAILABLE
    if not args.get("club_id"):
        raise ValueError("club_id is required")
    cal = _wrap(team.calendar, session, args["club_id"], _day(args.get("start"), "start"), _day(args.get("end"), "end"))
    keep = ("title", "type", "date", "start_time", "duration_min", "distance_m", "description", "status", "participants", "i_took_part")
    out = {"available": True, "from": cal["from"], "to": cal["to"], "sessions": [{k: s[k] for k in keep} for s in cal["sessions"]],
           "note": "A team session is a plan for the club, not a completed workout. Participants is a count."}
    if args.get("include_summary"):
        out["summary"] = _wrap(team.team_summary, session, args["club_id"], _day(args.get("start"), "start"), _day(args.get("end"), "end"))
    return out


def _get_club_challenges(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx)
    if not svc.available():
        return _UNAVAILABLE
    if not args.get("club_id"):
        raise ValueError("club_id is required")
    if args.get("challenge_id") is not None:
        c = _wrap(challenges.get_challenge, session, args["club_id"], int(args["challenge_id"]))
        keep = ("id", "title", "description", "metric", "start", "end", "goal", "phase", "participants", "joined", "my_value", "rules", "settles_on")
        return {"available": True, "challenge": {k: c.get(k) for k in keep}, "standings": [{k: r[k] for k in ("rank", "name", "value", "is_me")} for r in c["standings"]],
                "note": "Equal scores share a rank. Scores come from members' own connected-source activities; nothing about weight, calories or recovery is used."}
    keep = ("id", "title", "metric", "start", "end", "goal", "phase", "status", "participants", "joined", "my_value")
    return {"available": True, "challenges": [{k: c[k] for k in keep} for c in _wrap(challenges.list_challenges, session, args["club_id"])]}


def _get_club_leaderboard(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx)
    if not svc.available():
        return _UNAVAILABLE
    if not args.get("club_id"):
        raise ValueError("club_id is required")
    data = _wrap(team.club_leaderboard, session, args["club_id"], args.get("board") or "2000m")
    shape = lambda rows: [{k: r[k] for k in ("rank", "name", "result", "split_500m", "verification_label", "source", "is_me")} for r in rows]  # noqa: E731
    return {"available": True, "board": data["board_label"], "ranked": shape(data["ranked"]), "unverified": shape(data["unverified"]), "note": data["note"]}


_CLUB = {"type": "string", "description": "A club id from get_my_clubs."}

TOOLS: dict[str, dict] = {
    "get_my_clubs": {
        "fn": _get_my_clubs,
        "write": False,
        "description": "The clubs the athlete belongs to (their role, member count, and for staff what is waiting for approval), plus any join requests still waiting. "
        "Read-only. Public deployment only.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    "get_club": {
        "fn": _get_club,
        "write": False,
        "description": "One club the athlete is in (or a public club): description, rules, who it is for, and for a member the member handles and roles and the latest "
        "published announcements. Members are shown by the handle they chose. Never any member's training or health data.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {"club_id": _CLUB}, "required": ["club_id"]},
    },
    "get_club_calendar": {
        "fn": _get_club_calendar,
        "write": False,
        "description": "A club's planned team sessions between two dates, with how many members took part. A planned session is never a completed workout. "
        "Pass include_summary for aggregate team totals (shown only when at least three members chose to share a number).",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "club_id": _CLUB, "start": {"type": "string", "description": "YYYY-MM-DD"}, "end": {"type": "string", "description": "YYYY-MM-DD"},
            "include_summary": {"type": "boolean"}}, "required": ["club_id"]},
    },
    "get_club_challenges": {
        "fn": _get_club_challenges,
        "write": False,
        "description": "A club's group challenges. With no challenge_id it lists them; with one it returns the rules in plain words and the ranked standings "
        "(equal scores share a rank). Distance and time challenges are capped by design and consistency rewards regular weeks, never extra volume.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {"club_id": _CLUB, "challenge_id": {"type": "integer"}}, "required": ["club_id"]},
    },
    "get_club_leaderboard": {
        "fn": _get_club_leaderboard,
        "write": False,
        "description": "A club's results board for one distance or time: only results members explicitly shared with the club (plus public results of members who chose to "
        "show them there). Only verified results are ranked; equal results share a rank.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {"club_id": _CLUB, "board": {"type": "string", "enum": list(lb.BOARDS)}}, "required": ["club_id"]},
    },
}
