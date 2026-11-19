"""Clubs (session 27; docs/clubs.md §10): the few things that cannot run as the person asking.

Almost everything in clubs runs as the signed-in member under RLS (catch/sync/clubs.py). What lives here instead:

  * a member COUNT for discovery and an invite lookup by its unguessable token (a non-member can't read either table, by design);
  * ownership transfer (a two-row swap the one-owner index forces into a fixed order) — on Postgres this calls the SECURITY DEFINER
    catch_club.transfer_ownership, which re-checks that the caller is the owner;
  * deleting a club or a member's rows (SQLite has no cascades; on Postgres the cascade does the same work);
  * account deletion's succession rules, and platform moderation (CATCH_MODERATOR_IDS) with the report threshold.

System work runs through `leaderboard_store.store()` (a fresh Session under tenant.system_detached(): the bare `catch_api` role, which
migration 0006 gave permissive policies on the club tables for exactly this). Nothing here is reachable except through this module's
functions, and each takes the acting person explicitly."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete as sa_delete
from sqlalchemy import text, update as sa_update
from sqlmodel import Session, func, select

from catch.analytics import clubs as c
from catch.core import tenant_hooks
from catch.core.models import (
    Club, ClubAnnouncement, ClubAudit, ClubChallenge, ClubChallengeClaim, ClubChallengeEntry, ClubInvite, ClubJoinRequest, ClubLogo, ClubMember,
    ClubMemberPrefs, ClubProfile, ClubReport, ClubResult, ClubSession, ClubSessionParticipation,
)
from catch.sync.leaderboard_store import StoreError, store as system_session

REPORT_AUTO_HIDE_AT = 3  # distinct reporters who hide an announcement pending a moderator's look (same threshold as leaderboard results)
MODERATOR_ACTIONS = ("suspend_club", "restore_club", "hide_announcement", "restore_announcement", "remove_member", "dismiss_reports")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _sys_audit(s: Session, club_id: str, action: str, reason: str, *, kind: str = "system", actor: Optional[str] = None, subject: Optional[str] = None,
               target_type: Optional[str] = None, target_id: Optional[str] = None) -> None:
    s.add(ClubAudit(club_id=club_id, actor_id=actor, actor_kind=kind, action=action, target_type=target_type, target_id=target_id,
                    subject_owner_id=subject, reason_text=(reason or "").strip()[:c.REASON_MAX] or "—"))


# ---------------------------------------------------------------- discovery and invites

def member_counts(club_ids: list[str]) -> dict[str, int]:
    if not club_ids:
        return {}
    with system_session() as s:
        rows = s.exec(select(ClubMember.club_id, func.count()).where(ClubMember.club_id.in_(club_ids), ClubMember.status == "active").group_by(ClubMember.club_id)).all()  # type: ignore[attr-defined]
        return {club_id: n for club_id, n in rows}


def invite_preview(token: str) -> Optional[dict]:
    """The club behind a valid invite link, or None. Revoked, expired, used-up and suspended-club invites all look the same: nothing."""
    with system_session() as s:
        for h in c.invite_hash_candidates(token):
            inv = s.exec(select(ClubInvite).where(ClubInvite.token_hash == h)).first()
            if inv is None:
                continue
            club = s.get(Club, inv.club_id)
            if club is None or club.status != "active" or inv.revoked_at is not None or _aware(inv.expires_at) < _now():
                return None
            if inv.max_uses is not None:
                used = s.exec(select(func.count()).select_from(ClubJoinRequest).where(ClubJoinRequest.via_invite_id == inv.id)).one()
                if used >= inv.max_uses:
                    return None
            return {"invite_id": inv.id, "club_id": club.club_id, "name": club.name, "description": club.description, "audience": club.audience,
                    "visibility": club.visibility, "join_policy": club.join_policy, "rules": club.rules, "role": inv.role}
    return None


def club_row(club_id: str) -> Optional[Club]:
    """A detached copy of a club's row, for someone who holds a valid invite or an approval but is not (yet) a member and so can't read it
    under RLS. Never attached to a session and never written back."""
    with system_session() as s:
        k = s.get(Club, club_id)
        if k is None:
            return None
        return Club(club_id=k.club_id, name=k.name, name_ci=k.name_ci, description=k.description, location=k.location, visibility=k.visibility, audience=k.audience,
                    join_policy=k.join_policy, rules=k.rules, status=k.status, has_logo=k.has_logo, created_by=k.created_by, created_at=k.created_at)


# ---------------------------------------------------------------- ownership, deletion

def transfer_ownership(session: Session, club_id: str, actor: str, target: str) -> None:
    if tenant_hooks.uses_rls(session.get_bind()):
        session.execute(text("SELECT catch_club.transfer_ownership(:c, :t)"), {"c": club_id, "t": target})  # re-checks that the caller is the owner
        return
    old, new = session.get(ClubMember, (club_id, actor)), session.get(ClubMember, (club_id, target))
    if old is None or old.role != "owner" or new is None or new.status != "active":
        raise StoreError("Not allowed.", 403)
    old.role = "admin"
    session.add(old)
    session.flush()
    new.role = "owner"
    session.add(new)


def _delete_member_rows(s: Session, club_id: str, owner_id: str) -> None:
    for model in (ClubChallengeEntry, ClubSessionParticipation, ClubResult, ClubMemberPrefs):
        s.exec(sa_delete(model).where(model.club_id == club_id, model.owner_id == owner_id))  # type: ignore[attr-defined]


def forget_member(session: Session, club_id: str, owner_id: str) -> None:
    """A member leaving: their own rows in this club, then the membership. Challenge claims stay (the activity stays spoken for)."""
    _delete_member_rows(session, club_id, owner_id)
    session.exec(sa_delete(ClubMember).where(ClubMember.club_id == club_id, ClubMember.owner_id == owner_id))


def _delete_club(s: Session, club_id: str) -> None:
    challenge_ids = [i for (i,) in s.exec(select(ClubChallenge.id).where(ClubChallenge.club_id == club_id)).all()]
    if challenge_ids:
        s.exec(sa_delete(ClubChallengeClaim).where(ClubChallengeClaim.challenge_id.in_(challenge_ids)))  # type: ignore[attr-defined]
    for model in (ClubChallengeEntry, ClubSessionParticipation, ClubResult, ClubMemberPrefs):
        s.exec(sa_delete(model).where(model.club_id == club_id))  # type: ignore[attr-defined]
    for model in (ClubChallenge, ClubSession, ClubAnnouncement, ClubReport, ClubJoinRequest, ClubInvite, ClubMember):
        s.exec(sa_delete(model).where(model.club_id == club_id))  # type: ignore[attr-defined]
    s.exec(sa_delete(ClubLogo).where(ClubLogo.club_id == club_id))
    s.exec(sa_delete(Club).where(Club.club_id == club_id))


def delete_club_rows(session: Session, club_id: str) -> None:
    """The owner deletes a club. On Postgres this is one DELETE as the owner (RLS admits only the owner) and the cascade does the rest."""
    if tenant_hooks.uses_rls(session.get_bind()):
        session.exec(sa_delete(Club).where(Club.club_id == club_id))
    else:
        _delete_club(session, club_id)


def delete_owner_data(owner_id: str) -> None:
    """Account deletion. A club the person owned goes to its longest-standing eligible admin, then coach, then (adult clubs) athlete; with
    no one eligible it is deleted. Their own rows go; what they wrote (posts, decisions, reports) stays, detached from them, so a club's
    history and a moderator's trail remain explainable."""
    order = {"admin": 0, "coach": 1, "athlete": 2}
    with system_session() as s:
        for m in s.exec(select(ClubMember).where(ClubMember.owner_id == owner_id)).all():
            if m.role != "owner" or m.status != "active":
                continue
            club = s.get(Club, m.club_id)
            others = s.exec(select(ClubMember).where(ClubMember.club_id == m.club_id, ClubMember.status == "active", ClubMember.owner_id != owner_id)).all()
            eligible = sorted([o for o in others if c.may_hold_role(o.age_class, "owner", club.audience if club else "adult") is None], key=lambda o: (order.get(o.role, 3), _aware(o.joined_at)))
            if club is None:
                continue
            if eligible:
                _delete_member_rows(s, m.club_id, owner_id)
                s.exec(sa_delete(ClubMember).where(ClubMember.club_id == m.club_id, ClubMember.owner_id == owner_id))
                s.flush()
                eligible[0].role = "owner"
                s.add(eligible[0])
                _sys_audit(s, m.club_id, "ownership_transferred_on_account_deletion", "The owner deleted their account; the longest-standing eligible member took over.", subject=eligible[0].owner_id)
            else:
                _sys_audit(s, m.club_id, "club_deleted_owner_left_no_successor", "The owner deleted their account and no member could take over.")
                _delete_club(s, m.club_id)
            s.flush()
        for model in (ClubChallengeEntry, ClubSessionParticipation, ClubResult, ClubMemberPrefs):
            s.exec(sa_delete(model).where(model.owner_id == owner_id))  # type: ignore[attr-defined]
        s.exec(sa_delete(ClubChallengeClaim).where(ClubChallengeClaim.owner_id == owner_id))
        s.exec(sa_delete(ClubJoinRequest).where(ClubJoinRequest.owner_id == owner_id))
        s.exec(sa_delete(ClubMember).where(ClubMember.owner_id == owner_id))
        s.exec(sa_delete(ClubReport).where(ClubReport.target_type == "member", ClubReport.target_id == owner_id))
        s.exec(sa_delete(ClubProfile).where(ClubProfile.owner_id == owner_id))
        s.exec(sa_update(ClubReport).where(ClubReport.reporter_id == owner_id).values(reporter_id=None))
        s.exec(sa_update(ClubAnnouncement).where(ClubAnnouncement.author_id == owner_id).values(author_id=None))
        s.exec(sa_update(ClubSession).where(ClubSession.created_by == owner_id).values(created_by=None))
        s.exec(sa_update(ClubChallenge).where(ClubChallenge.created_by == owner_id).values(created_by=None))
        s.exec(sa_update(ClubInvite).where(ClubInvite.created_by == owner_id).values(created_by=None))
        s.exec(sa_update(ClubJoinRequest).where(ClubJoinRequest.decided_by == owner_id).values(decided_by=None))
        s.exec(sa_update(Club).where(Club.created_by == owner_id).values(created_by=None))
        s.exec(sa_update(ClubAudit).where(ClubAudit.actor_id == owner_id).values(actor_id=None))
        s.exec(sa_update(ClubAudit).where(ClubAudit.subject_owner_id == owner_id).values(subject_owner_id=None))
        s.commit()


# ---------------------------------------------------------------- reports and moderation

def after_report(club_id: str, target_type: str, target_id: str) -> None:
    """Three distinct reporters take an announcement down until a moderator looks. Nothing else auto-acts: a club, a member or a challenge is
    judged by a person, because a few accounts could otherwise silence a club by reporting it."""
    if target_type != "announcement":
        return
    with system_session() as s:
        from catch.sync import account_store

        # Only reports from accounts at least a week old count towards the automatic hide (a moderator still sees them all).
        reporters = account_store.eligible_reporters(
            s.exec(select(ClubReport.reporter_id).where(ClubReport.target_type == "announcement", ClubReport.target_id == target_id, ClubReport.status == "open")).all(), s
        )
        post = s.get(ClubAnnouncement, int(target_id))
        if reporters >= REPORT_AUTO_HIDE_AT and post is not None and post.status == "published":
            post.status, post.decided_by, post.decision_reason, post.decided_at = "hidden", None, "Hidden after reports, pending a moderator's review.", _now()
            s.add(post)
            _sys_audit(s, club_id, "post_auto_hidden", f"Hidden after {reporters} separate reports; a moderator will review it.", target_type="announcement", target_id=target_id)
            s.commit()


def queue(limit: int = 50) -> list[dict]:
    """Open reports grouped by target, most reported first. Reporters are never included."""
    with system_session() as s:
        rows = s.exec(select(ClubReport).where(ClubReport.status == "open").limit(2000)).all()
        groups: dict[tuple, dict] = {}
        for r in rows:
            g = groups.setdefault((r.club_id, r.target_type, r.target_id), {"club_id": r.club_id, "target_type": r.target_type, "target_id": r.target_id, "reports": 0,
                                                                          "reasons": set(), "first_at": _aware(r.created_at)})
            g["reports"] += 1
            g["reasons"].add(r.reason)
            g["first_at"] = min(g["first_at"], _aware(r.created_at))
        names = {k.club_id: k for k in s.exec(select(Club).where(Club.club_id.in_({k[0] for k in groups}))).all()} if groups else {}  # type: ignore[attr-defined]
        out = [{**g, "reasons": sorted(g["reasons"]), "first_at": g["first_at"].isoformat(), "club_name": names[g["club_id"]].name if g["club_id"] in names else "(deleted)",
                "club_status": names[g["club_id"]].status if g["club_id"] in names else None, "audience": names[g["club_id"]].audience if g["club_id"] in names else None}
               for g in groups.values()]
        out.sort(key=lambda g: (-g["reports"], g["first_at"]))
        return out[:limit]


def club_for_moderator(club_id: str) -> Optional[dict]:
    with system_session() as s:
        club = s.get(Club, club_id)
        if club is None:
            return None
        reports = s.exec(select(ClubReport).where(ClubReport.club_id == club_id, ClubReport.status == "open").order_by(ClubReport.id)).all()  # type: ignore[arg-type]
        events = s.exec(select(ClubAudit).where(ClubAudit.club_id == club_id).order_by(ClubAudit.id.desc()).limit(50)).all()  # type: ignore[attr-defined]
        count = s.exec(select(func.count()).select_from(ClubMember).where(ClubMember.club_id == club_id, ClubMember.status == "active")).one()
        posts = s.exec(select(ClubAnnouncement).where(ClubAnnouncement.club_id == club_id).order_by(ClubAnnouncement.id.desc()).limit(20)).all()  # type: ignore[attr-defined]
        member_targets = {r.target_id for r in reports if r.target_type == "member"}
        profiles = {p.owner_id: p for p in s.exec(select(ClubProfile).where(ClubProfile.owner_id.in_(member_targets))).all()} if member_targets else {}  # type: ignore[attr-defined]
        return {
            "club": {"club_id": club.club_id, "name": club.name, "audience": club.audience, "visibility": club.visibility, "status": club.status, "member_count": count,
                     "description": club.description, "rules": club.rules},
            "reports": [{"target_type": r.target_type, "target_id": r.target_id, "reason": r.reason, "detail": r.detail, "at": _aware(r.created_at).isoformat(),
                         "about": (profiles[r.target_id].handle if r.target_type == "member" and r.target_id in profiles else None)} for r in reports],  # no reporter, ever
            "announcements": [{"id": p.id, "title": p.title, "body": p.body, "status": p.status} for p in posts],
            "events": [{"action": e.action, "actor_kind": e.actor_kind, "reason": e.reason_text, "at": _aware(e.created_at).isoformat()} for e in events],
        }


def moderate(moderator_id: str, club_id: str, action: str, reason: str, target_id: Optional[str] = None, target_type: Optional[str] = None) -> dict:
    if action not in MODERATOR_ACTIONS:
        raise StoreError(f"action must be one of {', '.join(MODERATOR_ACTIONS)}")
    reason = " ".join((reason or "").split())
    if not reason:
        raise StoreError("A reason is required.")
    with system_session() as s:
        club = s.get(Club, club_id)
        if club is None:
            raise StoreError("Not found.", 404)
        if s.get(ClubMember, (club_id, moderator_id)) is not None:
            raise StoreError("You can't moderate a club you belong to.", 403)
        done = {"action": action}
        if action in ("suspend_club", "restore_club"):
            club.status = "suspended" if action == "suspend_club" else "active"
            s.add(club)
            s.exec(sa_update(ClubReport).where(ClubReport.club_id == club_id, ClubReport.target_type == "club", ClubReport.status == "open").values(status="actioned"))
        elif action in ("hide_announcement", "restore_announcement"):
            post = s.get(ClubAnnouncement, int(target_id)) if target_id and str(target_id).isdigit() else None
            if post is None or post.club_id != club_id:
                raise StoreError("Not found.", 404)
            post.status, post.decided_by, post.decision_reason, post.decided_at = ("hidden" if action == "hide_announcement" else "published"), moderator_id, reason[:c.REASON_MAX], _now()
            s.add(post)
            s.exec(sa_update(ClubReport).where(ClubReport.target_type == "announcement", ClubReport.target_id == str(post.id), ClubReport.status == "open")
                   .values(status="actioned" if action == "hide_announcement" else "dismissed"))
        elif action == "remove_member":
            m = s.get(ClubMember, (club_id, target_id or ""))
            if m is None or m.status != "active" or m.role == "owner":
                raise StoreError("Not found, or the owner can't be removed this way. Suspend the club instead.", 404)
            m.status = "removed"
            s.add(m)
            s.exec(sa_update(ClubResult).where(ClubResult.club_id == club_id, ClubResult.owner_id == m.owner_id).values(status="hidden"))
            s.exec(sa_update(ClubReport).where(ClubReport.club_id == club_id, ClubReport.target_type == "member", ClubReport.target_id == m.owner_id, ClubReport.status == "open").values(status="actioned"))
        else:  # dismiss_reports
            if target_type not in c.REPORT_TARGETS or not target_id:
                raise StoreError("Say which reports to dismiss.")
            s.exec(sa_update(ClubReport).where(ClubReport.club_id == club_id, ClubReport.target_type == target_type, ClubReport.target_id == target_id, ClubReport.status == "open").values(status="dismissed"))
        _sys_audit(s, club_id, f"moderator_{action}", reason, kind="moderator", actor=moderator_id, target_type=target_type or ("member" if action == "remove_member" else None), target_id=target_id,
                   subject=target_id if action == "remove_member" else None)
        s.commit()
        return done
