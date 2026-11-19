"""The deleted-account tombstone (global table, reached only through leaderboard_store.store(), like the other global
tables). Nothing here touches an owned table."""

from __future__ import annotations

from sqlmodel import select

from catch.core.models import DeletedAccount
from catch.sync.leaderboard_store import store


def is_deleted(user_id: str) -> bool:
    with store() as s:
        return s.exec(select(DeletedAccount).where(DeletedAccount.user_id == user_id)).first() is not None


def mark_deleted(user_id: str) -> None:
    with store() as s:
        if s.get(DeletedAccount, user_id) is None:
            s.add(DeletedAccount(user_id=user_id))
            s.commit()


def unmark_deleted(user_id: str) -> None:
    with store() as s:
        row = s.get(DeletedAccount, user_id)
        if row is not None:
            s.delete(row)
            s.commit()


# ---- the person's own rows in the global tables (export + "what is public about me") ---------------------------------------------
# table -> the column that names this person. Content other people wrote, and a club's own rows, are not "mine" to export.
OWNER_COLUMN = {
    "public_athletes": "owner_id",
    "public_entries": "owner_id",
    "result_reports": "reporter_id",
    "appeals": "owner_id",
    "moderation_events": "subject_owner_id",
    "club_profiles": "owner_id",
    "club_members": "owner_id",
    "club_member_prefs": "owner_id",
    "club_join_requests": "owner_id",
    "club_announcements": "author_id",
    "club_session_participation": "owner_id",
    "club_challenge_entries": "owner_id",
    "club_challenge_claims": "owner_id",
    "club_results": "owner_id",
    "club_reports": "reporter_id",
    "club_audit": "subject_owner_id",
}


def _table_class(name: str):
    from sqlmodel import SQLModel

    for mapper in SQLModel._sa_registry.mappers:
        if getattr(mapper.class_, "__tablename__", None) == name:
            return mapper.class_
    raise KeyError(name)


def iter_global_rows(owner_id: str, table: str, batch: int = 200):
    """This person's rows in one global table, in batches (bounded memory)."""
    cls = _table_class(table)
    column = getattr(cls, OWNER_COLUMN[table])
    with store() as s:
        stmt = select(cls).where(column == owner_id).execution_options(yield_per=batch)
        for row in s.scalars(stmt):
            yield row


def exposure(owner_id: str) -> dict:
    """What other people can see about this person right now, as counts (the Privacy page's 'public visibility' block)."""
    from sqlalchemy import func

    from catch.core.models import ClubMember, PublicAthlete, PublicEntry

    with store() as s:
        athlete = s.exec(select(PublicAthlete).where(PublicAthlete.owner_id == owner_id)).first()
        active_entries = s.exec(select(func.count()).select_from(PublicEntry).where(PublicEntry.owner_id == owner_id, PublicEntry.status == "active")).one()
        clubs = s.exec(select(func.count()).select_from(ClubMember).where(ClubMember.owner_id == owner_id, ClubMember.status == "active")).one()
        return {
            "leaderboard_profile": None if athlete is None else {"active": athlete.active, "display_mode": athlete.display_mode},
            "published_results": active_entries,
            "club_memberships": clubs,
        }


def prune_global(now=None) -> dict:
    """Retention for the global tables that hold per-person moderation traces (docs/legal/data-deletion-policy.md): resolved club
    reports after 12 months, the club audit trail after 24 (the database enforces that second age itself). Moderation decisions on
    leaderboard entries are kept — they must stay explainable — and are a retention question for counsel (docs/security-findings.md)."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import delete as sa_delete

    from catch.core.models import ClubAudit, ClubReport

    now = now or datetime.now(timezone.utc)
    with store() as s:
        reports = s.execute(sa_delete(ClubReport).where(ClubReport.status != "open", ClubReport.created_at < now - timedelta(days=365))).rowcount or 0
        audit = s.execute(sa_delete(ClubAudit).where(ClubAudit.created_at < now - timedelta(days=730))).rowcount or 0
        s.commit()
    return {"club_reports": reports, "club_audit": audit}
