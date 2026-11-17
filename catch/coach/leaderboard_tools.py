from __future__ import annotations

"""Session 26 (docs/leaderboards.md): three READ-ONLY leaderboard tools, merged into catch.coach.tools.TOOLS.

They go through the same service the REST routes use, so every figure is rendered by the one public serializer and carries
nothing an athlete hasn't chosen to publish. `get_verified_results` is the calling athlete's own results (with their
verification state) and never an exact date. There is deliberately no publish or unpublish tool: putting a result on a public
board is the athlete's own confirmed act in the app, not something an assistant or MCP client can do."""

from sqlmodel import Session

from catch.analytics import leaderboards as lb
from catch.analytics import verification as vf
from catch.core import principal as pr
from catch.core.principal import principal_from
from catch.sync import leaderboards as svc

_UNAVAILABLE = {"available": False, "reason": "Leaderboards exist only on the public deployment."}
_LIMIT_MAX = 50


def _athlete(ctx: dict) -> None:
    if principal_from(ctx).role != pr.ATHLETE_ROLE:
        raise ValueError("Only the athlete's own session can use the leaderboard tools.")


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.LeaderboardError as exc:
        raise ValueError(str(exc)) from None


def _get_leaderboards(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx)
    if not svc.available():
        return _UNAVAILABLE
    key = args.get("board")
    if not key:
        return {"available": True, "boards": svc.board_list(), "age_bands": list(lb.AGE_LABELS),
                "note": "Pass `board` to read one. Only verified results are ranked; each athlete appears once; equal results share a rank."}
    limit = max(1, min(int(args.get("limit") or 20), _LIMIT_MAX))
    data = _wrap(svc.board, session, key, age=args.get("age"), weight=args.get("weight"), club=args.get("club"),
                 verification=args.get("verification") or "verified", limit=limit)
    return {"available": True, **{k: data[k] for k in ("context", "entries", "unverified", "you", "total")}}


def _get_public_athlete_profile(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx)
    if not svc.available():
        return _UNAVAILABLE
    if args.get("athlete_id"):
        return {"available": True, **_wrap(svc.athlete_profile, args["athlete_id"])}
    return {"available": True, **_wrap(svc.my_profile_preview, session)}


def _get_verified_results(session: Session, args: dict, ctx: dict) -> dict:
    _athlete(ctx)
    if not svc.available():
        return _UNAVAILABLE
    state = args.get("state") or "verified"
    if state not in vf.STATES:
        raise ValueError(f"state must be one of {', '.join(vf.STATES)}")
    rows = _wrap(svc.my_results, session, board=args.get("board"), state=state, limit=_LIMIT_MAX)
    keep = ("ref", "board_key", "board_label", "result", "split_500m", "verification", "verification_label", "verification_explained", "published")
    return {"available": True, "state": state, "results": [{k: r[k] for k in keep} for r in rows],
            "meaning": vf.EXPLANATION[state]}


_BOARD = {"type": "string", "enum": list(lb.BOARDS)}

TOOLS: dict[str, dict] = {
    "get_leaderboards": {
        "fn": _get_leaderboards,
        "write": False,
        "description": "Public rowing leaderboards (500/1000/2000/5000/6000 m and 30/60 minutes). With no `board` it lists the boards. "
        "With one it returns a ranked page with its filters spelled out: only verified results are ranked, each athlete once, equal "
        "results share a rank. Public information only; names are the handles athletes chose. Public deployment only.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "board": _BOARD,
                "age": {"type": "string", "enum": list(lb.AGE_LABELS), "description": "Age category (U-bands are cumulative: U16 is under 16)."},
                "weight": {"type": "string", "enum": ["any", "lightweight"]},
                "club": {"type": "string", "description": "A club id."},
                "verification": {"type": "string", "enum": ["verified", "include_unverified"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": _LIMIT_MAX},
            },
        },
    },
    "get_public_athlete_profile": {
        "fn": _get_public_athlete_profile,
        "write": False,
        "description": "What the public can see of one athlete: the name they chose (or Anonymous rower) and their published best results, "
        "each with its verification status. Pass `athlete_id` (from a leaderboard row); omit it for the athlete's own public profile "
        "exactly as others see it. Never includes recovery, sleep, HRV, weight, nutrition, training history, provider ids or exact dates "
        "the athlete has not chosen to show.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {"athlete_id": {"type": "string"}}},
    },
    "get_verified_results": {
        "fn": _get_verified_results,
        "write": False,
        "description": "The athlete's own erg results that qualify for a leaderboard, with each one's verification state "
        "(verified = fetched through their own Concept2 account and flagged verified by Concept2; provider_linked; unverified) and whether "
        "it is published. Defaults to verified results. Read-only: publishing or taking down a result is something only the athlete does in the app.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"board": _BOARD, "state": {"type": "string", "enum": list(vf.STATES)}},
        },
    },
}
