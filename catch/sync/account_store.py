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
    # Fetched inside the store context and yielded outside it (a context manager held across a yield breaks under StreamingResponse).
    # One person's rows in one table are small, so a full fetch is bounded.
    with store() as s:
        rows = list(s.scalars(select(cls).where(column == owner_id)))
    yield from rows


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
    from sqlalchemy import func

    from catch.core.models import OAuthClient

    with store() as s:
        # Dynamic client registration is unauthenticated, so abandoned registrations are dropped: nothing used in 30 days.
        clients = s.execute(sa_delete(OAuthClient).where(func.coalesce(OAuthClient.last_used_at, OAuthClient.created_at) < now - timedelta(days=30))).rowcount or 0
        reports = s.execute(sa_delete(ClubReport).where(ClubReport.status != "open", ClubReport.created_at < now - timedelta(days=365))).rowcount or 0
        audit = s.execute(sa_delete(ClubAudit).where(ClubAudit.created_at < now - timedelta(days=730))).rowcount or 0
        s.commit()
    return {"club_reports": reports, "club_audit": audit, "oauth_clients": clients}


def account_age_days(owner_id: str, session=None) -> int | None:
    """Days since this account was created, or None if it doesn't exist. user_profiles is not readable by the runtime role on
    Postgres, so that path goes through one narrow SECURITY DEFINER function (migration 0008). Pass the caller's own store session
    when it has one open: a second session would hold a second connection at the same time."""
    from contextlib import nullcontext

    from sqlalchemy import text

    from catch.core import tenant_hooks
    from catch.core.models import UserProfile

    with (nullcontext(session) if session is not None else store()) as s:
        if tenant_hooks.uses_rls(s.get_bind()):
            return s.connection().execute(text("SELECT catch_private.account_age_days(:u)"), {"u": owner_id}).scalar()
        row = s.execute(select(UserProfile).where(UserProfile.id == owner_id).execution_options(tenant_unscoped=True)).scalar_one_or_none()
        if row is None:
            return None
        from datetime import datetime, timezone

        created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).days


MIN_REPORTER_AGE_DAYS = 7


def eligible_reporters(reporter_ids, session=None) -> int:
    """How many of these reporters count towards an automatic hide: accounts at least a week old, so three throwaway accounts made
    for the purpose can't take someone's result or post down. A moderator still sees every report."""
    return sum(1 for r in set(reporter_ids) if r and (account_age_days(r, session) or 0) >= MIN_REPORTER_AGE_DAYS)


def log_moderator_access(moderator_id: str, kind: str, target_id: str | None = None) -> None:
    from catch.core.models import ModeratorAccess

    with store() as s:
        s.add(ModeratorAccess(moderator_id=moderator_id, kind=kind, target_id=target_id))
        s.commit()
