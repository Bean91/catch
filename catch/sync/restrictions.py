"""Account restrictions and their appeals (session 28; docs/community-guidelines, docs/security.md "Moderation").

A platform moderator can restrict one account from one social capability — publishing results, clubs, or posting — with a mandatory
reason, for a stated time or until lifted. The person always sees the restriction, its reason and who decided (a platform
moderator), and can appeal once; another look can overturn it. What a restriction can never do: stop the person reading, exporting
or deleting their own data, disconnecting a provider, or deleting their account. Every action is an append-only row."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import select

from catch.core.config import settings
from catch.core.models import AccountRestriction, ModerationAction
from catch.sync.account_store import account_age_days
from catch.sync.leaderboard_store import store

SCOPES = ("publish", "clubs", "posting")
REASON_MAX = 500
SCOPE_TEXT = {"publish": "publishing results", "clubs": "creating or joining clubs", "posting": "posting in clubs"}


class RestrictionError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Restricted(RestrictionError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _active(r: AccountRestriction, now: datetime) -> bool:
    return r.lifted_at is None and (r.expires_at is None or _aware(r.expires_at) > now)


def _dict(r: AccountRestriction, now: datetime) -> dict:
    return {
        "id": r.id, "scope": r.scope, "scope_text": SCOPE_TEXT[r.scope], "active": _active(r, now), "reason_code": r.reason_code, "reason": r.reason_text,
        "decided_by": "a platform moderator", "created_at": _aware(r.created_at).isoformat(),
        "expires_at": _aware(r.expires_at).isoformat() if r.expires_at else None, "lifted_at": _aware(r.lifted_at).isoformat() if r.lifted_at else None,
        "appeal": None if r.appeal_status is None else {"status": r.appeal_status, "text": r.appeal_text, "resolution": r.appeal_resolution},
    }


def assert_allowed(owner_id: str, scope: str) -> None:
    now = _now()
    with store() as s:
        rows = s.exec(select(AccountRestriction).where(AccountRestriction.user_id == owner_id, AccountRestriction.scope == scope)).all()
    if any(_active(r, now) for r in rows):
        raise Restricted(f"You can't do this right now: {SCOPE_TEXT[scope]} is restricted on your account. Open Settings → Privacy to see why and to appeal.", 403)


def mine(owner_id: str) -> list[dict]:
    now = _now()
    with store() as s:
        rows = s.exec(select(AccountRestriction).where(AccountRestriction.user_id == owner_id).order_by(AccountRestriction.id.desc())).all()  # type: ignore[attr-defined]
        return [_dict(r, now) for r in rows]


def appeal(owner_id: str, restriction_id: int, text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise RestrictionError("Say why you think this should change.")
    if len(text) > REASON_MAX:
        raise RestrictionError(f"An appeal is at most {REASON_MAX} characters.")
    with store() as s:
        r = s.get(AccountRestriction, restriction_id)
        if r is None or r.user_id != owner_id:
            raise RestrictionError("Not found.", 404)
        if not _active(r, _now()):
            raise RestrictionError("This restriction is no longer in force.")
        if r.appeal_status is not None:
            raise RestrictionError("You have already appealed this restriction.", 409)
        r.appeal_text, r.appeal_status, r.appealed_at = text, "open", _now()
        s.commit()
        return _dict(r, _now())


# ---- moderator side ----------------------------------------------------------------------------------------------------------

def _reason(reason: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise RestrictionError("A reason is required.")
    return reason[:REASON_MAX]


def restrict(moderator_id: str, user_id: str, scope: str, reason_code: str, reason: str, days: Optional[int] = None) -> dict:
    if scope not in SCOPES:
        raise RestrictionError(f"scope must be one of {', '.join(SCOPES)}")
    reason = _reason(reason)
    if user_id == moderator_id:
        raise RestrictionError("You can't restrict your own account.", 403)
    if user_id in settings.moderators:
        raise RestrictionError("A moderator account can't be restricted this way.", 403)
    if days is not None and not (1 <= days <= 365):
        raise RestrictionError("days must be between 1 and 365 (or omit it for until lifted).")
    if account_age_days(user_id) is None:
        raise RestrictionError("No such account.", 404)
    now = _now()
    with store() as s:
        r = AccountRestriction(user_id=user_id, scope=scope, reason_code=(reason_code or "other")[:40], reason_text=reason, set_by=moderator_id,
                               expires_at=now + timedelta(days=days) if days else None)
        s.add(r)
        s.flush()
        s.add(ModerationAction(actor_id=moderator_id, action="restrict", subject_user_id=user_id, restriction_id=r.id, reason_text=reason))
        s.commit()
        return _dict(r, now)


def lift(moderator_id: str, restriction_id: int, reason: str) -> dict:
    reason = _reason(reason)
    with store() as s:
        r = s.get(AccountRestriction, restriction_id)
        if r is None:
            raise RestrictionError("Not found.", 404)
        if r.lifted_at is not None:
            raise RestrictionError("Already lifted.", 409)
        r.lifted_at, r.lifted_by = _now(), moderator_id
        s.add(ModerationAction(actor_id=moderator_id, action="lift", subject_user_id=r.user_id, restriction_id=r.id, reason_text=reason))
        s.commit()
        return _dict(r, _now())


def resolve_appeal(moderator_id: str, restriction_id: int, outcome: str, reason: str) -> dict:
    if outcome not in ("upheld", "overturned"):
        raise RestrictionError("outcome must be upheld or overturned")
    reason = _reason(reason)
    with store() as s:
        r = s.get(AccountRestriction, restriction_id)
        if r is None or r.appeal_status != "open":
            raise RestrictionError("Not found.", 404)
        if r.set_by == moderator_id:
            raise RestrictionError("A different moderator has to review an appeal of your own decision.", 403)
        r.appeal_status, r.appeal_resolution = outcome, reason
        if outcome == "overturned":
            r.lifted_at, r.lifted_by = _now(), moderator_id
        s.add(ModerationAction(actor_id=moderator_id, action=f"appeal_{outcome}", subject_user_id=r.user_id, restriction_id=r.id, reason_text=reason))
        s.commit()
        return _dict(r, _now())


def queue() -> list[dict]:
    """Active restrictions and any open appeals, newest first. Ids and reasons only — nothing from the person's own records."""
    now = _now()
    with store() as s:
        rows = s.exec(select(AccountRestriction).order_by(AccountRestriction.id.desc()).limit(200)).all()  # type: ignore[attr-defined]
        return [{**_dict(r, now), "user_id": r.user_id, "set_by": r.set_by} for r in rows if _active(r, now) or r.appeal_status == "open"]


def actions(limit: int = 200) -> list[dict]:
    with store() as s:
        rows = s.exec(select(ModerationAction).order_by(ModerationAction.id.desc()).limit(max(1, min(limit, 500)))).all()  # type: ignore[attr-defined]
        return [{"id": a.id, "actor_id": a.actor_id, "action": a.action, "subject_user_id": a.subject_user_id, "restriction_id": a.restriction_id,
                 "reason": a.reason_text, "at": _aware(a.created_at).isoformat()} for a in rows]
