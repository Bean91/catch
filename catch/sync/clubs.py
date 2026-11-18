"""Clubs (session 27; docs/clubs.md): the athlete-facing service. Public deployment only.

Every function acts as the *current owner* (`tenant.current_owner()`) over the request's own Session, so on Postgres every statement
runs as the `authenticated` role under migration 0006's membership policies. This module ALSO checks role and membership itself (the
matrix in analytics/clubs.py) before it writes, so a person gets a clear 403/404 rather than a database error, and so the SQLite test
suite exercises the same rules. The two layers say the same thing: tests/pg/test_clubs.py runs every actor/target combination through both.

Another person is never named by their account id on the wire. A member is addressed by a per-club reference (`member_ref`, a keyed hash
of club id + account id), so a response in one club can't be used to recognise the same person in another."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from catch.analytics import clubs as c
from catch.core import config, tenant
from catch.core.models import (
    Club, ClubAnnouncement, ClubAudit, ClubBlock, ClubChallenge, ClubInvite, ClubJoinRequest, ClubMember,
    ClubMemberPrefs, ClubProfile, ClubReport, ClubResult, ClubSession,
)
from catch.sync import club_store as store

CLUBS_CREATED_PER_DAY = 3
REPORTS_PER_DAY = 10
PENDING_REQUESTS_PER_PERSON = 5
APPROVAL_VALID = timedelta(days=c.JOIN_APPROVAL_VALID_DAYS)


class ClubError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def available() -> bool:
    return tenant.is_public()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)  # SQLite hands back naive datetimes


def me() -> str:
    return tenant.current_owner()


def _secret() -> str:
    return config.settings.secrets_master_key or config.settings.fernet_key or "catch-clubs"


def member_ref(club_id: str, owner_id: str) -> str:
    return hmac.new(_secret().encode(), f"member:{club_id}:{owner_id}".encode(), hashlib.sha256).hexdigest()[:20]


def _value(fn, *args, **kw):
    """Run a pure validator, turning its ValueError into a 400 the person can act on."""
    try:
        return fn(*args, **kw)
    except ValueError as exc:
        raise ClubError(str(exc)) from None


# ---------------------------------------------------------------- lookups shared with club_team / club_challenges

def membership(session: Session, club_id: str, owner_id: Optional[str] = None) -> Optional[ClubMember]:
    m = session.get(ClubMember, (club_id, owner_id or me()))
    return m if m is not None and m.status == "active" else None


def require_member(session: Session, club_id: str, action: Optional[str] = None) -> tuple[Club, ClubMember]:
    """404 for a club this person can't see (never a 403 that confirms it exists); 403 when they're in but their role may not do `action`."""
    club = session.get(Club, club_id)
    m = membership(session, club_id) if club is not None else None
    if club is None or m is None:
        raise ClubError("Not found.", 404)
    if action and not c.can(m.role, action):
        raise ClubError("Your role in this club can't do that.", 403)
    return club, m


def handles(session: Session, owner_ids: set[str]) -> dict[str, ClubProfile]:
    if not owner_ids:
        return {}
    return {p.owner_id: p for p in session.exec(select(ClubProfile).where(ClubProfile.owner_id.in_(owner_ids))).all()}  # type: ignore[attr-defined]


def my_blocks(session: Session) -> set[str]:
    return {b.blocked_owner_id for b in session.exec(select(ClubBlock)).all()}  # owned table: only mine


def resolve_member(session: Session, club: Club, ref: str, *, include_removed: bool = False) -> ClubMember:
    for m in session.exec(select(ClubMember).where(ClubMember.club_id == club.club_id).limit(5000)).all():
        if (include_removed or m.status == "active") and hmac.compare_digest(member_ref(club.club_id, m.owner_id), ref or ""):
            return m
    raise ClubError("Not found.", 404)


def audit(session: Session, club_id: str, action: str, reason: str, *, kind: str = "member", target_type: Optional[str] = None,
          target_id: Optional[str] = None, subject: Optional[str] = None, actor: Optional[str] = None) -> None:
    session.add(ClubAudit(club_id=club_id, actor_id=actor if actor is not None else me(), actor_kind=kind, action=action, target_type=target_type,
                          target_id=target_id, subject_owner_id=subject, reason_text=(reason or "").strip()[:c.REASON_MAX] or "—"))


# ---------------------------------------------------------------- profile

def _profile_dict(p: Optional[ClubProfile]) -> dict:
    if p is None:
        return {"exists": False, "bands": list(c.CLUB_AGE_BANDS), "min_age": 13, "guardian_below": 16}
    return {"exists": True, "handle": p.handle, "age_band": p.age_band, "age_class": p.age_class, "guardian_consent": p.guardian_consent_at is not None,
            "bands": list(c.CLUB_AGE_BANDS), "min_age": 13, "guardian_below": 16}


def get_profile(session: Session) -> dict:
    return _profile_dict(session.get(ClubProfile, me()))


def set_profile(session: Session, *, handle: str, age_band: str, attest_min_age: bool, guardian_consent: bool = False) -> dict:
    from catch.analytics import leaderboards as lb

    handle = _value(lb.validate_handle, handle)
    age_class = _value(c.age_class_for_band, age_band)
    if not attest_min_age:
        raise ClubError("Confirm you are 13 or older to use clubs.")
    if c.guardian_required(age_band) and not guardian_consent:
        raise ClubError("A parent or guardian must agree before someone under 16 can join a club. Tick the guardian box to confirm they do.")
    existing = session.get(ClubProfile, me())
    if existing is not None and existing.age_class != age_class and membership_count(session) > 0:
        raise ClubError("You're in a club that needs your current age group. Leave your clubs before changing between adult and under-19.", 409)
    p = existing or ClubProfile(owner_id=me(), handle=handle, handle_ci=handle.lower(), age_band=age_band, age_class=age_class)
    p.handle, p.handle_ci, p.age_band, p.age_class, p.updated_at = handle, handle.lower(), age_band, age_class, _now()
    p.guardian_consent_at = (p.guardian_consent_at or _now()) if (guardian_consent and c.guardian_required(age_band)) else None
    session.add(p)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ClubError("That handle is taken. Try another.", 409) from None
    return _profile_dict(p)


def membership_count(session: Session) -> int:
    return session.exec(select(func.count()).select_from(ClubMember).where(ClubMember.owner_id == me(), ClubMember.status == "active")).one()


def _need_profile(session: Session) -> ClubProfile:
    p = session.get(ClubProfile, me())
    if p is None:
        raise ClubError("Choose a club handle and age group first.", 428)
    return p


# ---------------------------------------------------------------- clubs

def _club_dict(club: Club, *, role: Optional[str] = None, count: Optional[int] = None, pending: Optional[dict] = None) -> dict:
    out = {
        "club_id": club.club_id, "name": club.name, "description": club.description, "location": club.location, "visibility": club.visibility,
        "audience": club.audience, "join_policy": club.join_policy, "rules": club.rules, "status": club.status, "has_logo": club.has_logo,
        "member_count": count, "my_role": role, "capabilities": c.capabilities(role, club.audience) if role else None,
        "created_at": _aware(club.created_at).isoformat() if club.created_at else None,
    }
    if pending is not None:
        out["pending"] = pending
    return out


def create_club(session: Session, **raw) -> dict:
    profile = _need_profile(session)
    if profile.age_class != "adult":
        raise ClubError("Only adults can start a club. Ask a coach to start a junior club.", 403)
    since = _now() - timedelta(days=1)
    made = session.exec(select(func.count()).select_from(Club).where(Club.created_by == me(), Club.created_at > since)).one()
    if made >= CLUBS_CREATED_PER_DAY:
        raise ClubError("You've started several clubs today. Try again tomorrow.", 429)
    f = _value(c.validate_club_fields, **raw)
    club = Club(club_id=str(uuid.uuid4()), name=f.name, name_ci=f.name.lower(), description=f.description, location=f.location, visibility=f.visibility,
                audience=f.audience, join_policy=f.join_policy, rules=f.rules, created_by=me())
    session.add(club)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise ClubError("A club with that name already exists.", 409) from None
    session.add(ClubMember(club_id=club.club_id, owner_id=me(), club_audience=club.audience, role="owner", age_class="adult"))
    session.flush()
    session.add(ClubMemberPrefs(club_id=club.club_id, owner_id=me(), rules_accepted_at=_now()))
    audit(session, club.club_id, "club_created", f"{club.audience} club, {club.visibility}", kind="staff")
    session.commit()
    return _club_dict(club, role="owner", count=1)


def discover(session: Session, q: Optional[str] = None, limit: int = 30) -> list[dict]:
    """Public, adult, active clubs only (a junior or private club is never listed). A count, never a member list."""
    stmt = select(Club).where(Club.visibility == "public", Club.audience == "adult", Club.status == "active")
    if q:
        stmt = stmt.where(Club.name_ci.contains(" ".join(q.lower().split())[:40]))  # type: ignore[attr-defined]
    clubs = session.exec(stmt.order_by(Club.name_ci).limit(max(1, min(limit, 50)))).all()
    counts = store.member_counts([k.club_id for k in clubs])
    mine = {m.club_id: m.role for m in session.exec(select(ClubMember).where(ClubMember.owner_id == me(), ClubMember.status == "active")).all()}
    return [{**_club_dict(k, role=mine.get(k.club_id), count=counts.get(k.club_id, 0)), "joined": k.club_id in mine} for k in clubs]


def my_clubs(session: Session) -> dict:
    complete_approved(session)
    rows = session.exec(select(ClubMember).where(ClubMember.owner_id == me(), ClubMember.status == "active")).all()
    clubs = {k.club_id: k for k in session.exec(select(Club).where(Club.club_id.in_([m.club_id for m in rows]))).all()} if rows else {}  # type: ignore[attr-defined]
    counts = store.member_counts(list(clubs))
    out = []
    for m in rows:
        k = clubs.get(m.club_id)
        if k is None:
            continue
        pending = None
        if c.can(m.role, "see_requests"):
            pending = {
                "requests": session.exec(select(func.count()).select_from(ClubJoinRequest).where(ClubJoinRequest.club_id == k.club_id, ClubJoinRequest.status == "pending")).one(),
                "posts": session.exec(select(func.count()).select_from(ClubAnnouncement).where(ClubAnnouncement.club_id == k.club_id, ClubAnnouncement.status == "pending")).one()
                + session.exec(select(func.count()).select_from(ClubSession).where(ClubSession.club_id == k.club_id, ClubSession.status == "pending")).one()
                + session.exec(select(func.count()).select_from(ClubChallenge).where(ClubChallenge.club_id == k.club_id, ClubChallenge.status == "pending")).one(),
            }
        out.append(_club_dict(k, role=m.role, count=counts.get(k.club_id, 0), pending=pending))
    out.sort(key=lambda d: d["name"].lower())
    return {"clubs": out, "profile": get_profile(session), "requests": my_requests(session)}


def get_club(session: Session, club_id: str) -> dict:
    club = session.get(Club, club_id)
    if club is None:
        raise ClubError("Not found.", 404)
    m = membership(session, club_id)
    counts = store.member_counts([club_id])
    if m is None:
        if not (club.visibility == "public" and club.audience == "adult" and club.status == "active"):
            raise ClubError("Not found.", 404)  # a private or junior club doesn't admit it exists
        d = _club_dict(club, count=counts.get(club_id, 0))
        d["description_only"] = True
        return d
    d = _club_dict(club, role=m.role, count=counts.get(club_id, 0))
    prefs = session.get(ClubMemberPrefs, (club_id, me()))
    d["my_prefs"] = {"include_public_results": bool(prefs and prefs.include_public_results), "share_numbers": bool(prefs and prefs.share_numbers),
                     "rules_accepted": bool(prefs and prefs.rules_accepted_at)}
    return d


def update_club(session: Session, club_id: str, **raw) -> dict:
    club, m = require_member(session, club_id, "edit_club")
    merged = {"name": club.name, "description": club.description, "location": club.location, "visibility": club.visibility, "join_policy": club.join_policy, "rules": club.rules}
    merged.update({k: v for k, v in raw.items() if v is not None or k in ("description", "location", "rules")})
    f = _value(c.validate_club_fields, audience=club.audience, **merged)
    club.name, club.name_ci, club.description, club.location = f.name, f.name.lower(), f.description, f.location
    club.visibility, club.join_policy, club.rules = f.visibility, f.join_policy, f.rules
    session.add(club)
    audit(session, club_id, "club_updated", "settings changed", kind="staff")
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ClubError("A club with that name already exists.", 409) from None
    return get_club(session, club_id)


def delete_club(session: Session, club_id: str, *, confirm: bool) -> dict:
    club, m = require_member(session, club_id, "delete_club")
    if confirm is not True:
        return {"deleted": False, "preview": f"This permanently deletes {club.name}: its members, posts, sessions and challenges. Nothing is deleted until you confirm."}
    audit(session, club_id, "club_deleted", "deleted by the owner", kind="staff")
    store.delete_club_rows(session, club_id)
    session.commit()
    return {"deleted": True}


def leave_club(session: Session, club_id: str) -> dict:
    club, m = require_member(session, club_id, "leave")
    audit(session, club_id, "member_left", "left the club")
    session.flush()
    store.forget_member(session, club_id, me())
    session.commit()
    return {"left": True}


def transfer_ownership(session: Session, club_id: str, ref: str, *, confirm: bool) -> dict:
    club, m = require_member(session, club_id, "transfer_ownership")
    target = resolve_member(session, club, ref)
    if target.owner_id == me():
        raise ClubError("Choose another member.")
    problem = c.may_hold_role(target.age_class, "owner", club.audience)
    if problem:
        raise ClubError(problem)
    if confirm is not True:
        who = handles(session, {target.owner_id}).get(target.owner_id)
        return {"transferred": False, "preview": f"{who.handle if who else 'This member'} becomes the owner. You become an admin. Nothing changes until you confirm."}
    audit(session, club_id, "ownership_transferred", "ownership handed to another member", kind="staff", subject=target.owner_id)
    session.flush()
    store.transfer_ownership(session, club_id, me(), target.owner_id)
    session.commit()
    return {"transferred": True}


# ---------------------------------------------------------------- members and roles

def members(session: Session, club_id: str) -> dict:
    club, mine = require_member(session, club_id)
    rows = session.exec(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.status == "active").limit(2000)).all()
    profiles = handles(session, {r.owner_id for r in rows})
    blocked = my_blocks(session)
    staff = c.can(mine.role, "set_roles") or c.can(mine.role, "remove_member")
    out = []
    for r in rows:
        p = profiles.get(r.owner_id)
        hidden = r.owner_id in blocked
        entry = {
            "member_ref": member_ref(club_id, r.owner_id), "handle": ("Blocked member" if hidden and not staff else (p.handle if p else "Member")),
            "role": r.role, "joined": _aware(r.joined_at).strftime("%Y-%m") if r.joined_at else None, "is_me": r.owner_id == me(), "blocked": hidden,
            "can_manage": c.can_manage_member(mine.role, r.role, same_person=r.owner_id == me()),
        }
        if staff and club.audience == "junior" and r.age_class == "youth":
            entry["guardian_consent"] = bool(p and p.guardian_consent_at)  # a coach needs to know; no one else does
        out.append(entry)
    order = {role: i for i, role in enumerate(c.ROLES)}
    out.sort(key=lambda e: (order[e["role"]], e["handle"].lower()))
    return {"members": out, "count": len(out)}


def set_role(session: Session, club_id: str, ref: str, new_role: str, *, reason: Optional[str] = None) -> dict:
    club, mine = require_member(session, club_id, "set_roles")
    target = resolve_member(session, club, ref)
    if new_role not in c.ROLES or new_role == "owner":
        raise ClubError("Choose admin, coach or athlete. To hand over a club, transfer ownership.")
    if not c.can_manage_member(mine.role, target.role, same_person=target.owner_id == me()) or not c.can_assign_role(mine.role, new_role):
        raise ClubError("Your role can't make that change.", 403)
    problem = c.may_hold_role(target.age_class, new_role, club.audience)
    if problem:
        raise ClubError(problem)
    old = target.role
    target.role = new_role
    session.add(target)
    audit(session, club_id, "role_changed", _value(c.validate_reason, reason, required=False) or f"{old} to {new_role}", kind="staff", subject=target.owner_id)
    session.commit()
    return {"member_ref": ref, "role": new_role}


def remove_member(session: Session, club_id: str, ref: str, reason: str) -> dict:
    club, mine = require_member(session, club_id, "remove_member")
    target = resolve_member(session, club, ref)
    if not c.can_manage_member(mine.role, target.role, same_person=target.owner_id == me()):
        raise ClubError("Your role can't remove this member.", 403)
    reason = _value(c.validate_reason, reason)
    target.status = "removed"
    session.add(target)
    audit(session, club_id, "member_removed", reason, kind="staff", subject=target.owner_id)
    for res in session.exec(select(ClubResult).where(ClubResult.club_id == club_id, ClubResult.owner_id == target.owner_id)).all():
        res.status = "hidden"  # staff may hide a shared result (the member's own copy is theirs to delete)
        session.add(res)
    session.commit()
    return {"removed": True}


def set_prefs(session: Session, club_id: str, *, include_public_results: Optional[bool] = None, share_numbers: Optional[bool] = None, accept_rules: bool = False) -> dict:
    club, _ = require_member(session, club_id)
    p = session.get(ClubMemberPrefs, (club_id, me())) or ClubMemberPrefs(club_id=club_id, owner_id=me())
    if include_public_results is not None:
        if club.visibility == "private" or club.audience == "junior":
            include_public_results = False if club.audience == "junior" else include_public_results
        p.include_public_results = bool(include_public_results)
    if share_numbers is not None:
        p.share_numbers = bool(share_numbers)
    if accept_rules and p.rules_accepted_at is None:
        p.rules_accepted_at = _now()
    session.add(p)
    session.commit()
    return {"include_public_results": p.include_public_results, "share_numbers": p.share_numbers, "rules_accepted": p.rules_accepted_at is not None}


# ---------------------------------------------------------------- invites and joining

def _invite_dict(i: ClubInvite, token: Optional[str] = None, uses: Optional[int] = None) -> dict:
    exp = _aware(i.expires_at)
    state = "revoked" if i.revoked_at else ("expired" if exp < _now() else "active")
    return {"invite_id": i.id, "role": i.role, "state": state, "expires_at": exp.isoformat(), "max_uses": i.max_uses, "uses": uses, "token": token,
            "created_at": _aware(i.created_at).isoformat()}


def create_invite(session: Session, club_id: str, *, role: str = "athlete", days: Optional[int] = None, max_uses: Optional[int] = None) -> dict:
    club, mine = require_member(session, club_id, "see_requests")
    if role not in c.INVITE_ROLES:
        raise ClubError("An invite is for an athlete or a coach.")
    if not c.may_create_invite(mine.role, role):
        raise ClubError("Only an owner or admin can invite a coach.", 403)
    days_v, uses_v = _value(c.invite_expiry_days, days), _value(c.invite_max_uses, max_uses)
    token = c.new_invite_token()
    inv = ClubInvite(club_id=club_id, token_hash=c.invite_hash(token), role=role, created_by=me(), expires_at=_now() + timedelta(days=days_v), max_uses=uses_v)
    session.add(inv)
    session.flush()
    audit(session, club_id, "invite_created", f"{role} invite, {days_v} days", kind="staff", target_type="invite", target_id=str(inv.id))
    session.commit()
    return _invite_dict(inv, token=token, uses=0)  # the token is shown once; only its hash is stored


def list_invites(session: Session, club_id: str) -> list[dict]:
    require_member(session, club_id, "see_requests")
    rows = session.exec(select(ClubInvite).where(ClubInvite.club_id == club_id).order_by(ClubInvite.id.desc()).limit(50)).all()  # type: ignore[attr-defined]
    uses = {i.id: session.exec(select(func.count()).select_from(ClubJoinRequest).where(ClubJoinRequest.via_invite_id == i.id)).one() for i in rows}
    return [_invite_dict(i, uses=uses[i.id]) for i in rows]


def revoke_invite(session: Session, club_id: str, invite_id: int) -> dict:
    require_member(session, club_id, "see_requests")
    inv = session.get(ClubInvite, invite_id)
    if inv is None or inv.club_id != club_id:
        raise ClubError("Not found.", 404)
    if inv.revoked_at is None:
        inv.revoked_at = _now()
        session.add(inv)
        audit(session, club_id, "invite_revoked", "invite revoked", kind="staff", target_type="invite", target_id=str(invite_id))
        session.commit()
    return _invite_dict(inv)


def preview_invite(session: Session, token: str) -> dict:
    """What a person holding a link may see before anything is shared with them: the club's name, description, rules and who it is for."""
    found = store.invite_preview(token)
    if found is None:
        raise ClubError("This invite link isn't valid any more.", 404)
    profile = session.get(ClubProfile, me())
    reason = c.may_hold_role(profile.age_class, found["role"], found["audience"]) if profile else None
    existing = membership(session, found["club_id"])
    return {**{k: v for k, v in found.items() if k != "invite_id"}, "already_member": existing is not None, "needs_profile": profile is None,
            "cannot_join_because": reason, "will_need_approval": found["audience"] == "junior" or found["join_policy"] == "request"}


def _insert_membership(session: Session, club: Club, role: str, profile: ClubProfile, accept: bool) -> None:
    session.add(ClubMember(club_id=club.club_id, owner_id=me(), club_audience=club.audience, role=role, age_class=profile.age_class))
    session.flush()
    session.add(ClubMemberPrefs(club_id=club.club_id, owner_id=me(), rules_accepted_at=_now() if accept else None))
    audit(session, club.club_id, "member_joined", f"joined as {role}")


def join(session: Session, *, token: Optional[str] = None, club_id: Optional[str] = None, message: Optional[str] = None, accept_rules: bool = False) -> dict:
    """Open clubs admit directly; an invite admits directly to an adult 'invite' club; everything else (a request club, and EVERY junior club)
    becomes a request a coach or staff member decides. A removed member can't come back."""
    profile = _need_profile(session)
    inv_id: Optional[int] = None
    role = "athlete"
    if token:
        found = store.invite_preview(token)
        if found is None:
            raise ClubError("This invite link isn't valid any more.", 404)
        club_id, inv_id, role = found["club_id"], found["invite_id"], found["role"]
    if not club_id:
        raise ClubError("Choose a club or use an invite link.")
    club = store.club_row(club_id) if token else session.get(Club, club_id)  # an invite holder isn't a member yet, so RLS hides a private club from them
    if club is None or club.status != "active":
        raise ClubError("Not found.", 404)
    if not token and not (club.visibility == "public" and club.audience == "adult"):
        raise ClubError("Not found.", 404)  # a private or junior club can only be joined with its link
    prior = session.get(ClubMember, (club_id, me()))
    if prior is not None:
        raise ClubError("You're already in this club." if prior.status == "active" else "You can't rejoin this club.", 409 if prior.status == "active" else 403)
    problem = c.may_hold_role(profile.age_class, role, club.audience)
    if problem:
        raise ClubError(problem, 403)
    if club.audience == "junior" and role == "athlete" and c.guardian_required(profile.age_band) and profile.guardian_consent_at is None:
        raise ClubError("A parent or guardian's agreement is needed before joining. Add it on your club profile.", 428)
    if club.rules and not accept_rules:
        raise ClubError("Read and accept the club rules to join.", 428)
    message = _value(c.validate_message, message)
    direct = (club.join_policy == "open" and club.visibility == "public" and club.audience == "adult" and role == "athlete") or (club.join_policy == "invite" and club.audience == "adult" and inv_id)
    if direct:
        if inv_id:
            session.add(ClubJoinRequest(club_id=club_id, owner_id=me(), role=role, status="approved", via_invite_id=inv_id, decided_at=_now(), message=None))
            session.flush()
        _insert_membership(session, club, role, profile, accept_rules or not club.rules)
        session.commit()
        return {"status": "joined", "club_id": club_id}
    pending = session.exec(select(func.count()).select_from(ClubJoinRequest).where(ClubJoinRequest.owner_id == me(), ClubJoinRequest.status == "pending")).one()
    if pending >= PENDING_REQUESTS_PER_PERSON:
        raise ClubError("You have several requests waiting. Wait for a decision or withdraw one first.", 429)
    session.add(ClubJoinRequest(club_id=club_id, owner_id=me(), role=role, message=message, via_invite_id=inv_id))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ClubError("You've already asked to join this club.", 409) from None
    return {"status": "requested", "club_id": club_id, "needs": "a coach's approval" if club.audience == "junior" else "approval from the club"}


def my_requests(session: Session) -> list[dict]:
    rows = session.exec(select(ClubJoinRequest).where(ClubJoinRequest.owner_id == me()).order_by(ClubJoinRequest.id.desc()).limit(20)).all()  # type: ignore[attr-defined]
    names = {k.club_id: k.name for k in session.exec(select(Club).where(Club.club_id.in_({r.club_id for r in rows}))).all()} if rows else {}  # type: ignore[attr-defined]
    return [{"request_id": r.id, "club_id": r.club_id, "club_name": names.get(r.club_id, "A club"), "role": r.role, "status": r.status,
             "created_at": _aware(r.created_at).isoformat(), "decision_reason": r.decision_reason} for r in rows if names.get(r.club_id)]


def withdraw_request(session: Session, request_id: int) -> dict:
    r = session.get(ClubJoinRequest, request_id)
    if r is None or r.owner_id != me():
        raise ClubError("Not found.", 404)
    session.delete(r)
    session.commit()
    return {"withdrawn": True}


def complete_approved(session: Session) -> int:
    """An approved request is a window (14 days) to join, and joining is the applicant's own act, so it happens here, as them."""
    done = 0
    cutoff = _now() - APPROVAL_VALID
    for r in session.exec(select(ClubJoinRequest).where(ClubJoinRequest.owner_id == me(), ClubJoinRequest.status == "approved")).all():
        if session.get(ClubMember, (r.club_id, me())) is not None or _aware(r.decided_at or r.created_at) < cutoff:
            continue
        club, profile = store.club_row(r.club_id), session.get(ClubProfile, me())
        if club is None or profile is None or club.status != "active" or c.may_hold_role(profile.age_class, r.role, club.audience):
            continue
        _insert_membership(session, club, r.role, profile, True)
        session.delete(r)
        done += 1
    if done:
        session.commit()
    return done


def requests(session: Session, club_id: str) -> list[dict]:
    club, mine = require_member(session, club_id, "see_requests")
    rows = session.exec(select(ClubJoinRequest).where(ClubJoinRequest.club_id == club_id, ClubJoinRequest.status == "pending").order_by(ClubJoinRequest.id)).all()  # type: ignore[arg-type]
    profiles = handles(session, {r.owner_id for r in rows})
    out = []
    for r in rows:
        p = profiles.get(r.owner_id)
        out.append({"request_id": r.id, "handle": p.handle if p else "Applicant", "role": r.role, "age_class": p.age_class if p else None, "message": r.message,
                    "guardian_consent": bool(p and p.guardian_consent_at) if p and p.age_class == "youth" else None,
                    "created_at": _aware(r.created_at).isoformat(), "can_decide": c.may_decide_request(mine.role, club.audience, r.role)})
    return out


def decide_request(session: Session, club_id: str, request_id: int, *, approve: bool, reason: Optional[str] = None) -> dict:
    club, mine = require_member(session, club_id, "see_requests")
    r = session.get(ClubJoinRequest, request_id)
    if r is None or r.club_id != club_id or r.status != "pending":
        raise ClubError("Not found.", 404)
    if not c.may_decide_request(mine.role, club.audience, r.role):
        raise ClubError("In a junior club only a coach or the owner admits a young athlete; only an owner or admin admits a coach." if club.audience == "junior" or r.role == "coach"
                        else "Your role can't decide this request.", 403)
    reason_v = _value(c.validate_reason, reason, required=not approve)
    r.status, r.decided_by, r.decision_reason, r.decided_at = ("approved" if approve else "rejected"), me(), reason_v or None, _now()
    session.add(r)
    audit(session, club_id, "request_approved" if approve else "request_rejected", reason_v or "approved", kind="staff", subject=r.owner_id)
    session.commit()
    return {"status": r.status}


# ---------------------------------------------------------------- safety: blocks, reports, audit

def block(session: Session, club_id: str, ref: str) -> dict:
    club, _ = require_member(session, club_id, "block")
    target = resolve_member(session, club, ref)
    if target.owner_id == me():
        raise ClubError("You can't block yourself.")
    if session.get(ClubBlock, (me(), target.owner_id)) is None:
        session.add(ClubBlock(blocked_owner_id=target.owner_id))
        session.commit()
    return {"blocked": True}


def unblock(session: Session, club_id: str, ref: str) -> dict:
    club, _ = require_member(session, club_id, "block")
    target = resolve_member(session, club, ref)
    existing = session.get(ClubBlock, (me(), target.owner_id))
    if existing is not None:
        session.delete(existing)
        session.commit()
    return {"blocked": False}


def report(session: Session, club_id: str, target_type: str, target_id: str, reason: str, detail: Optional[str] = None) -> dict:
    """Reports are visible to the reporter and to platform moderators only. Staff of the club reported never see who reported."""
    club, _ = require_member(session, club_id, "report")
    if target_type not in c.REPORT_TARGETS or reason not in c.REPORT_REASONS:
        raise ClubError("Choose what you're reporting and why.")
    detail_v = _value(c.validate_reason, detail, required=False) or None
    if target_type == "club":
        target_id = club_id
    elif target_type == "announcement":
        a = session.get(ClubAnnouncement, int(target_id)) if str(target_id).isdigit() else None
        if a is None or a.club_id != club_id or a.status != "published":
            raise ClubError("Not found.", 404)
        target_id = str(a.id)
    elif target_type == "challenge":
        ch = session.get(ClubChallenge, int(target_id)) if str(target_id).isdigit() else None
        if ch is None or ch.club_id != club_id:
            raise ClubError("Not found.", 404)
        target_id = str(ch.id)
    else:
        target = resolve_member(session, club, target_id)
        if target.owner_id == me():
            raise ClubError("You can't report yourself.")
        target_id = target.owner_id  # the moderator needs the person; staff never see this table
    since = _now() - timedelta(days=1)
    if session.exec(select(func.count()).select_from(ClubReport).where(ClubReport.reporter_id == me(), ClubReport.created_at > since)).one() >= REPORTS_PER_DAY:
        raise ClubError("You've sent several reports today. A moderator will look at them.", 429)
    session.add(ClubReport(club_id=club_id, target_type=target_type, target_id=target_id, reporter_id=me(), reason=reason, detail=detail_v))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ClubError("You've already reported this.", 409) from None
    store.after_report(club_id, target_type, target_id)
    return {"reported": True, "message": "Thanks. A platform moderator will review this. The club's staff are not told who reported."}


def audit_log(session: Session, club_id: str, limit: int = 100) -> list[dict]:
    require_member(session, club_id, "see_audit")
    rows = session.exec(select(ClubAudit).where(ClubAudit.club_id == club_id).order_by(ClubAudit.id.desc()).limit(max(1, min(limit, 200)))).all()  # type: ignore[attr-defined]
    people = handles(session, {r.actor_id for r in rows if r.actor_id} | {r.subject_owner_id for r in rows if r.subject_owner_id})
    label = lambda oid: (people[oid].handle if oid in people else "a former member") if oid else None  # noqa: E731
    return [{"action": r.action, "by": ("a platform moderator" if r.actor_kind == "moderator" else "Catch" if r.actor_kind == "system" else label(r.actor_id)),
             "about": label(r.subject_owner_id), "reason": r.reason_text, "at": _aware(r.created_at).isoformat()} for r in rows]


# ---------------------------------------------------------------- logo

_IMAGE_MAGIC = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/webp": (b"RIFF",)}


def put_logo(session: Session, club_id: str, content_type: str, data: bytes) -> dict:
    club, _ = require_member(session, club_id, "edit_logo")
    if content_type not in _IMAGE_MAGIC or not any(data.startswith(m) for m in _IMAGE_MAGIC[content_type]):
        raise ClubError("Use a JPEG, PNG or WebP image.")
    if len(data) > c.LOGO_MAX_BYTES:
        raise ClubError("That image is too big. Logos are at most 256 KB.", 413)
    row = session.get(ClubLogoRow, club_id) or ClubLogoRow(club_id=club_id, content_type=content_type, data=data)
    row.content_type, row.data, row.updated_at = content_type, data, _now()
    session.add(row)
    club.has_logo = True
    session.add(club)
    audit(session, club_id, "logo_changed", "logo updated", kind="staff")
    session.commit()
    return {"has_logo": True}


def get_logo(session: Session, club_id: str) -> tuple[str, bytes]:
    club = session.get(Club, club_id)
    row = session.get(ClubLogoRow, club_id) if club is not None else None
    if club is None or row is None or not (membership(session, club_id) or (club.visibility == "public" and club.audience == "adult" and club.status == "active")):
        raise ClubError("Not found.", 404)
    return row.content_type, row.data


def delete_logo(session: Session, club_id: str) -> dict:
    club, _ = require_member(session, club_id, "edit_logo")
    row = session.get(ClubLogoRow, club_id)
    if row is not None:
        session.delete(row)
    club.has_logo = False
    session.add(club)
    audit(session, club_id, "logo_removed", "logo removed", kind="staff")
    session.commit()
    return {"has_logo": False}


from catch.core.models import ClubLogo as ClubLogoRow  # noqa: E402
