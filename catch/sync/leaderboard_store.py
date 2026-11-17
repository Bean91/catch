"""Session 26 (docs/leaderboards.md): the ONLY module that reads or writes the global leaderboard tables.

Those tables have no owner filter, so every path in here is a reviewed one: it opens a fresh Session outside any
owner's context (`tenant.system_detached`, which on Postgres keeps the connection as the bare `catch_api` role — the only
role with grants on them), takes the acting owner as an explicit argument, and checks ownership itself. Nothing here
touches an owned table, so it needs no raw SQL and no unscoped query."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from catch.analytics import leaderboards as lb
from catch.core import db as db_module
from catch.core import tenant
from catch.core.models import Appeal, Club, ClubMember, ModerationEvent, PublicAthlete, PublicEntry, ResultReport

REPORT_AUTO_HIDE_AT = 3
REPORTS_PER_DAY = 10
APPEALS_OPEN_MAX = 3

STATUSES = ("active", "hidden", "removed")
REPORT_REASONS = ("not_a_real_result", "wrong_category", "inappropriate_name_or_note", "other")
REASON_MAX = 500


class StoreError(ValueError):
    """A request the store refuses, with a message that is safe to show the caller."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


class DuplicateResult(StoreError):
    def __init__(self) -> None:
        super().__init__("That result can't be published.", 409)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def store() -> Iterator[Session]:
    with tenant.system_detached(), Session(db_module.engine) as session:
        yield session


# ---------------------------------------------------------------- athletes

def _athlete_dict(a: PublicAthlete) -> dict:
    return {"public_id": a.public_id, "owner_id": a.owner_id, "handle": a.handle, "display_mode": a.display_mode, "active": a.active, "age_group": a.age_group, "age_provenance": a.age_provenance}


def athlete_for_owner(owner_id: str) -> Optional[dict]:
    with store() as s:
        a = s.exec(select(PublicAthlete).where(PublicAthlete.owner_id == owner_id)).first()
        return _athlete_dict(a) if a else None


def athlete_by_public_id(public_id: str) -> Optional[dict]:
    with store() as s:
        a = s.get(PublicAthlete, public_id)
        return _athlete_dict(a) if a else None


def upsert_athlete(owner_id: str, *, handle: Optional[str], display_mode: str, active: bool = True) -> dict:
    """Create or update the public face of an athlete. Handles are unique case-insensitively across all athletes."""
    if display_mode not in lb.DISPLAY_MODES:
        raise StoreError("display mode must be handle or anonymous")
    with store() as s:
        a = s.exec(select(PublicAthlete).where(PublicAthlete.owner_id == owner_id)).first()
        if a is None:
            a = PublicAthlete(public_id=str(uuid.uuid4()), owner_id=owner_id)
            s.add(a)
        a.handle = handle
        a.handle_ci = handle.lower() if handle else None
        a.display_mode = display_mode
        a.active = active
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise StoreError("That handle is already taken.", 409) from None
        s.refresh(a)
        return _athlete_dict(a)


def set_athlete_age(owner_id: str, age_group: Optional[str], provenance: Optional[str]) -> None:
    with store() as s:
        s.exec(sa_update(PublicAthlete).where(PublicAthlete.owner_id == owner_id).values(age_group=age_group, age_provenance=provenance))
        s.commit()


# ---------------------------------------------------------------- the one status function

def set_entry_status(
    s: Session,
    entry: PublicEntry,
    to: str,
    *,
    actor_kind: str,
    actor_id: Optional[str],
    reason_code: str,
    reason_text: str,
) -> None:
    """Every change to an entry's standing goes through here, and leaves a moderation event in the same transaction. A
    reason is mandatory; nothing is hidden, removed or restored without one. `to` may also be "withdrawn" (the athlete
    took it down), which deletes the public row after recording why."""
    reason_text = (reason_text or "").strip()
    if not reason_text or not reason_code:
        raise StoreError("A reason is required.")
    if len(reason_text) > REASON_MAX:
        raise StoreError(f"A reason is at most {REASON_MAX} characters.")
    if to not in (*STATUSES, "withdrawn"):
        raise StoreError("unknown status")
    s.add(
        ModerationEvent(
            entry_id=entry.entry_id, subject_owner_id=entry.owner_id, from_status=entry.status, to_status=to,
            actor_kind=actor_kind, actor_id=actor_id, reason_code=reason_code, reason_text=reason_text,
        )
    )
    if to == "withdrawn":
        s.delete(entry)
    else:
        entry.status = to


def _entry_for_owner(s: Session, owner_id: str, entry_id: str) -> PublicEntry:
    entry = s.get(PublicEntry, entry_id)
    if entry is None or entry.owner_id != owner_id:
        raise StoreError("Not found.", 404)
    return entry


# ---------------------------------------------------------------- entries

def create_entry(owner_id: str, *, public_id: str, athlete_key: str, board_key: str, value: int, verification: str, provider: Optional[str],
                 provider_user_id: Optional[str], provider_result_id: Optional[str], age_years: Optional[int], age_band: Optional[str],
                 age_label: Optional[str], age_provenance: Optional[str], weight_class: Optional[str], date_label: Optional[str],
                 note: Optional[str]) -> str:
    entry_id = str(uuid.uuid4())
    with store() as s:
        s.add(
            PublicEntry(
                entry_id=entry_id, owner_id=owner_id, public_id=public_id, athlete_key=athlete_key, board_key=board_key, value=value,
                verification=verification, provider=provider, provider_user_id=provider_user_id, provider_result_id=provider_result_id,
                age_years=age_years, age_band=age_band, age_label=age_label, age_provenance=age_provenance, weight_class=weight_class,
                date_label=date_label, note=note, tiebreak=lb.tiebreak_for(entry_id),
            )
        )
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise DuplicateResult() from None
    return entry_id


def discard_unpublished(owner_id: str, entry_id: str) -> None:
    """Undo a create whose owner-side record then failed to save. The entry was never confirmed to the athlete."""
    with store() as s:
        s.exec(sa_delete(PublicEntry).where(PublicEntry.entry_id == entry_id, PublicEntry.owner_id == owner_id))
        s.commit()


def set_note(owner_id: str, entry_id: str, note: Optional[str]) -> None:
    with store() as s:
        _entry_for_owner(s, owner_id, entry_id).note = note
        s.commit()


def withdraw(owner_id: str, entry_id: str, *, reason_code: str = "user_withdrawn", reason_text: str = "Withdrawn by the athlete.") -> None:
    with store() as s:
        entry = _entry_for_owner(s, owner_id, entry_id)
        set_entry_status(s, entry, "withdrawn", actor_kind="user", actor_id=owner_id, reason_code=reason_code, reason_text=reason_text)
        s.commit()


def system_hide(owner_id: str, entry_id: str, reason_code: str, reason_text: str) -> bool:
    """An automatic hide (source changed). Only an active entry moves; returns whether it did."""
    with store() as s:
        entry = s.get(PublicEntry, entry_id)
        if entry is None or entry.owner_id != owner_id or entry.status != "active":
            return False
        set_entry_status(s, entry, "hidden", actor_kind="system", actor_id=None, reason_code=reason_code, reason_text=reason_text)
        s.commit()
        return True


def entry_statuses(owner_id: str) -> dict[str, str]:
    with store() as s:
        return {e.entry_id: e.status for e in s.exec(select(PublicEntry).where(PublicEntry.owner_id == owner_id)).all()}


def board_rows(board_key: str) -> list[dict]:
    """Every active entry on a board from an active athlete, with the fields ranking and filtering need. Capped."""
    with store() as s:
        rows = s.exec(
            select(PublicEntry, PublicAthlete)
            .join(PublicAthlete, PublicAthlete.public_id == PublicEntry.public_id)
            .where(PublicEntry.board_key == board_key, PublicEntry.status == "active", PublicAthlete.active == True)  # noqa: E712
            .limit(5000)
        ).all()
        clubs: dict[str, set[str]] = {}
        ids = {a.public_id for _, a in rows}
        if ids:
            for m in s.exec(select(ClubMember).where(ClubMember.public_id.in_(ids))).all():  # type: ignore[attr-defined]
                clubs.setdefault(m.public_id, set()).add(m.club_id)
        return [
            {
                "entry_id": e.entry_id, "owner_id": e.owner_id, "public_id": e.public_id, "athlete_key": e.athlete_key, "board_key": e.board_key,
                "value": e.value, "verification": e.verification, "tiebreak": e.tiebreak, "age_years": e.age_years, "age_band": e.age_band,
                "age_label": e.age_label, "age_provenance": e.age_provenance, "weight_class": e.weight_class, "date_label": e.date_label,
                "note": e.note, "handle": a.handle, "display_mode": a.display_mode, "clubs": clubs.get(e.public_id, set()),
            }
            for e, a in rows
        ]


def entries_for_athlete(public_id: str) -> list[dict]:
    with store() as s:
        a = s.get(PublicAthlete, public_id)
        if a is None or not a.active:
            return []
        entries = s.exec(select(PublicEntry).where(PublicEntry.public_id == public_id, PublicEntry.status == "active")).all()
        return [
            {"entry_id": e.entry_id, "board_key": e.board_key, "value": e.value, "verification": e.verification, "age_label": e.age_label,
             "age_provenance": e.age_provenance, "weight_class": e.weight_class, "date_label": e.date_label, "note": e.note}
            for e in entries
        ]


# ---------------------------------------------------------------- reports

def report(reporter_id: str, entry_id: str, reason: str, detail: Optional[str]) -> dict:
    if reason not in REPORT_REASONS:
        raise StoreError(f"reason must be one of {', '.join(REPORT_REASONS)}")
    detail = (detail or "").strip()[:REASON_MAX] or None
    with store() as s:
        entry = s.get(PublicEntry, entry_id)
        if entry is None or entry.status != "active":
            raise StoreError("Not found.", 404)
        if entry.owner_id == reporter_id:
            raise StoreError("You can't report your own result.")
        since = _now() - timedelta(days=1)
        today = s.exec(select(func.count()).select_from(ResultReport).where(ResultReport.reporter_id == reporter_id, ResultReport.created_at >= since)).one()
        if today >= REPORTS_PER_DAY:
            raise StoreError("You've reached today's report limit. Try again tomorrow.", 429)
        s.add(ResultReport(entry_id=entry_id, reporter_id=reporter_id, reason=reason, detail=detail))
        try:
            s.flush()
        except IntegrityError:
            s.rollback()
            raise StoreError("You've already reported this result.", 409) from None
        open_reporters = s.exec(select(func.count(func.distinct(ResultReport.reporter_id))).where(ResultReport.entry_id == entry_id, ResultReport.status == "open")).one()
        hidden = False
        if open_reporters >= REPORT_AUTO_HIDE_AT:
            set_entry_status(s, entry, "hidden", actor_kind="system", actor_id=None, reason_code="report_threshold",
                             reason_text=f"Hidden for review after {open_reporters} separate reports.")
            hidden = True
        s.commit()
        return {"reported": True, "hidden_for_review": hidden}


# ---------------------------------------------------------------- appeals (athlete side)

def my_events(owner_id: str) -> list[dict]:
    with store() as s:
        events = s.exec(select(ModerationEvent).where(ModerationEvent.subject_owner_id == owner_id).order_by(ModerationEvent.id.desc()).limit(200)).all()  # type: ignore[attr-defined]
        return [
            {"id": e.id, "entry_id": e.entry_id, "from_status": e.from_status, "to_status": e.to_status, "actor_kind": e.actor_kind,
             "reason_code": e.reason_code, "reason_text": e.reason_text, "created_at": e.created_at.isoformat()}
            for e in events
        ]


def my_appeals(owner_id: str) -> list[dict]:
    with store() as s:
        return [_appeal_dict(a) for a in s.exec(select(Appeal).where(Appeal.owner_id == owner_id).order_by(Appeal.id.desc())).all()]  # type: ignore[attr-defined]


def _appeal_dict(a: Appeal) -> dict:
    return {"id": a.id, "entry_id": a.entry_id, "text": a.text, "status": a.status, "resolution_text": a.resolution_text,
            "created_at": a.created_at.isoformat(), "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None}


def appeal(owner_id: str, entry_id: str, text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise StoreError("Say why you think this decision should change.")
    if len(text) > REASON_MAX:
        raise StoreError(f"An appeal is at most {REASON_MAX} characters.")
    with store() as s:
        entry = _entry_for_owner(s, owner_id, entry_id)
        if entry.status == "active":
            raise StoreError("Only a hidden or removed result can be appealed.")
        open_for_entry = s.exec(select(func.count()).select_from(Appeal).where(Appeal.entry_id == entry_id, Appeal.status == "open")).one()
        if open_for_entry:
            raise StoreError("This result already has an open appeal.", 409)
        open_total = s.exec(select(func.count()).select_from(Appeal).where(Appeal.owner_id == owner_id, Appeal.status == "open")).one()
        if open_total >= APPEALS_OPEN_MAX:
            raise StoreError("You have too many open appeals. Wait for a decision first.", 429)
        row = Appeal(entry_id=entry_id, owner_id=owner_id, text=text)
        s.add(row)
        s.commit()
        s.refresh(row)
        return _appeal_dict(row)


def withdraw_appeal(owner_id: str, appeal_id: int) -> None:
    with store() as s:
        row = s.get(Appeal, appeal_id)
        if row is None or row.owner_id != owner_id or row.status != "open":
            raise StoreError("Not found.", 404)
        row.status = "withdrawn"
        row.resolved_at = _now()
        s.commit()


# ---------------------------------------------------------------- moderation (moderator side)

def queue() -> dict:
    with store() as s:
        reported = s.exec(
            select(ResultReport.entry_id, func.count(func.distinct(ResultReport.reporter_id)), func.max(ResultReport.created_at))
            .where(ResultReport.status == "open").group_by(ResultReport.entry_id)
        ).all()
        appeals = s.exec(select(Appeal).where(Appeal.status == "open").order_by(Appeal.id)).all()  # type: ignore[arg-type]
        hidden = s.exec(select(PublicEntry).where(PublicEntry.status != "active").limit(200)).all()
        out_reports = []
        for entry_id, n, last in reported:
            e = s.get(PublicEntry, entry_id)
            if e is None:
                continue
            reasons = [r.reason for r in s.exec(select(ResultReport).where(ResultReport.entry_id == entry_id, ResultReport.status == "open")).all()]
            out_reports.append({"entry_id": entry_id, "reporters": n, "last_reported_at": last.isoformat(), "status": e.status, "board_key": e.board_key, "reasons": reasons})
        return {
            "reports": out_reports,
            "appeals": [{**_appeal_dict(a), "entry_status": (s.get(PublicEntry, a.entry_id).status if s.get(PublicEntry, a.entry_id) else None)} for a in appeals],
            "non_active": [{"entry_id": e.entry_id, "status": e.status, "board_key": e.board_key} for e in hidden],
        }


def entry_for_moderator(entry_id: str) -> Optional[dict]:
    with store() as s:
        e = s.get(PublicEntry, entry_id)
        a = s.get(PublicAthlete, e.public_id) if e else None
        if e is None or a is None:
            return None
        events = s.exec(select(ModerationEvent).where(ModerationEvent.entry_id == entry_id).order_by(ModerationEvent.id)).all()  # type: ignore[arg-type]
        return {
            "entry": {"entry_id": e.entry_id, "board_key": e.board_key, "value": e.value, "verification": e.verification, "status": e.status,
                      "handle": a.handle, "age_label": e.age_label, "weight_class": e.weight_class, "date_label": e.date_label, "note": e.note},
            "events": [{"from_status": x.from_status, "to_status": x.to_status, "actor_kind": x.actor_kind, "reason_code": x.reason_code,
                        "reason_text": x.reason_text, "created_at": x.created_at.isoformat()} for x in events],
        }


MODERATOR_ACTIONS = {"hide": "hidden", "remove": "removed", "restore": "active"}


def moderate(moderator_id: str, entry_id: str, action: str, reason: str) -> dict:
    if action not in MODERATOR_ACTIONS and action != "dismiss_reports":
        raise StoreError("action must be hide, remove, restore or dismiss_reports")
    with store() as s:
        entry = s.get(PublicEntry, entry_id)
        if entry is None:
            raise StoreError("Not found.", 404)
        if entry.owner_id == moderator_id:
            raise StoreError("You can't moderate your own result.", 403)
        if action == "dismiss_reports":
            reason = (reason or "").strip()
            if not reason:
                raise StoreError("A reason is required.")
            s.exec(sa_update(ResultReport).where(ResultReport.entry_id == entry_id, ResultReport.status == "open").values(status="dismissed"))
            s.add(ModerationEvent(entry_id=entry_id, subject_owner_id=entry.owner_id, from_status=entry.status, to_status=entry.status,
                                  actor_kind="moderator", actor_id=moderator_id, reason_code="reports_dismissed", reason_text=reason[:REASON_MAX]))
            s.commit()
            return {"status": entry.status}
        target = MODERATOR_ACTIONS[action]
        set_entry_status(s, entry, target, actor_kind="moderator", actor_id=moderator_id, reason_code=f"moderator_{action}", reason_text=reason)
        if target != "active":
            s.exec(sa_update(ResultReport).where(ResultReport.entry_id == entry_id, ResultReport.status == "open").values(status="actioned"))
        s.commit()
        return {"status": target}


def resolve_appeal(moderator_id: str, appeal_id: int, outcome: str, reason: str) -> dict:
    if outcome not in ("upheld", "overturned"):
        raise StoreError("outcome must be upheld or overturned")
    with store() as s:
        row = s.get(Appeal, appeal_id)
        if row is None or row.status != "open":
            raise StoreError("Not found.", 404)
        entry = s.get(PublicEntry, row.entry_id)
        if entry is None:
            raise StoreError("Not found.", 404)
        if entry.owner_id == moderator_id:
            raise StoreError("You can't moderate your own result.", 403)
        reason = (reason or "").strip()
        if not reason:
            raise StoreError("A reason is required.")
        if outcome == "overturned" and entry.status != "active":
            set_entry_status(s, entry, "active", actor_kind="moderator", actor_id=moderator_id, reason_code="appeal_overturned", reason_text=reason)
        else:
            s.add(ModerationEvent(entry_id=entry.entry_id, subject_owner_id=entry.owner_id, from_status=entry.status, to_status=entry.status,
                                  actor_kind="moderator", actor_id=moderator_id, reason_code=f"appeal_{outcome}", reason_text=reason[:REASON_MAX]))
        row.status, row.resolution_text, row.resolved_by, row.resolved_at = outcome, reason[:REASON_MAX], moderator_id, _now()
        s.commit()
        return _appeal_dict(row)


# ---------------------------------------------------------------- clubs

def _code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def create_club(owner_id: str, public_id: str, name: str) -> dict:
    name = " ".join((name or "").split())
    if not (3 <= len(name) <= 40) or lb._URL_RE.search(name):
        raise StoreError("A club name is 3-40 characters and can't contain a web address.")
    code = secrets.token_hex(4).upper()
    with store() as s:
        club = Club(club_id=str(uuid.uuid4()), name=name, name_ci=name.lower(), code_hash=_code_hash(code), created_by=owner_id)
        s.add(club)
        s.add(ClubMember(club_id=club.club_id, public_id=public_id))
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise StoreError("A club with that name already exists.", 409) from None
        return {"club_id": club.club_id, "name": club.name, "join_code": code}


def join_club(public_id: str, code: str) -> dict:
    with store() as s:
        club = s.exec(select(Club).where(Club.code_hash == _code_hash(code or ""))).first()
        if club is None:
            raise StoreError("That join code isn't valid.", 404)
        if s.get(ClubMember, (club.club_id, public_id)) is None:
            s.add(ClubMember(club_id=club.club_id, public_id=public_id))
            s.commit()
        return {"club_id": club.club_id, "name": club.name}


def leave_club(public_id: str, club_id: str) -> None:
    with store() as s:
        s.exec(sa_delete(ClubMember).where(ClubMember.club_id == club_id, ClubMember.public_id == public_id))
        s.commit()


def clubs_of(public_id: str) -> list[dict]:
    with store() as s:
        rows = s.exec(select(Club).join(ClubMember, ClubMember.club_id == Club.club_id).where(ClubMember.public_id == public_id)).all()
        return [{"club_id": c.club_id, "name": c.name} for c in rows]


# ---------------------------------------------------------------- account deletion / opt-out

def withdraw_all(owner_id: str, reason_code: str, reason_text: str) -> int:
    with store() as s:
        entries = s.exec(select(PublicEntry).where(PublicEntry.owner_id == owner_id)).all()
        for e in entries:
            set_entry_status(s, e, "withdrawn", actor_kind="user", actor_id=owner_id, reason_code=reason_code, reason_text=reason_text)
        s.commit()
        return len(entries)


def delete_owner_data(owner_id: str) -> None:
    """Account deletion. Public rows and the athlete's own reports/appeals go; the audit log stays but is detached from the
    person (no owner id), because a moderation decision must remain explainable after the account is gone."""
    with store() as s:
        athlete = s.exec(select(PublicAthlete).where(PublicAthlete.owner_id == owner_id)).first()
        if athlete is not None:
            s.exec(sa_delete(ClubMember).where(ClubMember.public_id == athlete.public_id))
        s.exec(sa_delete(PublicEntry).where(PublicEntry.owner_id == owner_id))
        if athlete is not None:
            s.delete(athlete)
        s.exec(sa_update(ResultReport).where(ResultReport.reporter_id == owner_id).values(reporter_id=None))
        s.exec(sa_delete(Appeal).where(Appeal.owner_id == owner_id))
        s.exec(sa_update(ModerationEvent).where(ModerationEvent.subject_owner_id == owner_id).values(subject_owner_id=None))
        s.exec(sa_update(ModerationEvent).where(ModerationEvent.actor_id == owner_id).values(actor_id=None))
        s.commit()
