"""Clubs (session 27; docs/clubs.md): the pure half. Roles and the one permission matrix, the junior-club invariants, text and
field validation, invite tokens, and the aggregate suppression that keeps a team summary from describing one person.

No I/O. Every rule here that guards data is ALSO a CHECK constraint or an RLS predicate in migration 0006 (`catch_club.*`);
tests/pg/test_clubs.py proves the database refuses what this module says is refused, and tests/test_clubs_schema.py asserts
the vocabularies below equal the CHECK lists, so the two can't drift apart quietly.

Naming: a club's `coach` role is unrelated to a coach *device token* or the in-app AI coach (docs/clubs.md §2)."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Iterable, Optional

from catch.analytics import leaderboards as lb

ROLES = ("owner", "admin", "coach", "athlete")
STAFF_ROLES = ("owner", "admin", "coach")
JUNIOR_COACH_ROLES = ("owner", "coach")  # a junior club's owner is automatically a coach for approvals and direct posting; an admin is not
ADMIN_ROLES = ("owner", "admin")
AUDIENCES = ("adult", "junior")
VISIBILITIES = ("public", "private")
JOIN_POLICIES = ("open", "request", "invite")
CLUB_STATUSES = ("active", "suspended")
MEMBER_STATUSES = ("active", "removed")
AGE_CLASSES = ("adult", "youth")
INVITE_ROLES = ("athlete", "coach")
POST_STATUSES = ("pending", "published", "rejected", "hidden")
SESSION_STATUSES = ("pending", "published", "cancelled", "rejected")
CHALLENGE_STATUSES = ("pending", "active", "cancelled", "rejected")
REQUEST_STATUSES = ("pending", "approved", "rejected")
REPORT_TARGETS = ("club", "announcement", "member", "challenge")
REPORT_REASONS = ("harassment", "unsafe", "inappropriate", "impersonation", "spam", "other")
SESSION_TYPES = ("erg", "on_water", "run", "bike", "strength", "cross", "test", "other")

NAME_MIN, NAME_MAX = 3, 40
DESCRIPTION_MAX, LOCATION_MAX, RULES_MAX = 500, 80, 2000
TITLE_MAX, BODY_MAX = 80, 2000
MESSAGE_MAX, REASON_MAX = 300, 500
INVITE_DAYS_DEFAULT, INVITE_DAYS_MAX = 7, 30
INVITE_MAX_USES_CAP = 100
JOIN_APPROVAL_VALID_DAYS = 14  # mirrors catch_club.join_allowed: an approval is a window to join, not a permanent pass
K_MIN = 3  # a total or mean is reported only when at least this many members contributed to it
LOGO_MAX_BYTES = 262144

# ---------------------------------------------------------------- age

YOUTH_BANDS = tuple(f"U{n}" for n in lb.YOUTH_UNDER)
CLUB_AGE_BANDS = ("adult",) + YOUTH_BANDS


def age_class_for_band(band: str) -> str:
    """Self-declared, like the leaderboards' age category: Catch cannot verify anyone's age (docs/clubs.md §4)."""
    if band not in CLUB_AGE_BANDS:
        raise ValueError("choose an age group from the list")
    return "youth" if band in YOUTH_BANDS else "adult"


def guardian_required(band: str) -> bool:
    """Reuses session 26's threshold: under 16 needs a recorded guardian-consent tick (U14, U15, U16)."""
    return band in YOUTH_BANDS and int(band[1:]) <= lb.GUARDIAN_CONSENT_BELOW


# ---------------------------------------------------------------- permission matrix

def can_assign_role(actor: Optional[str], new_role: str) -> bool:
    """Mirrors catch_club.can_assign_role: nobody makes an owner (that is a transfer) and nobody makes a peer or superior."""
    return {"owner": new_role in ("admin", "coach", "athlete"), "admin": new_role in ("coach", "athlete"), "coach": new_role == "athlete"}.get(actor or "", False)


def can_manage_member(actor: Optional[str], target_role: str, *, same_person: bool = False) -> bool:
    """Mirrors catch_club.can_manage_member: change a role, or remove. Never yourself, never someone at or above your level."""
    if same_person:
        return False
    return {"owner": target_role != "owner", "admin": target_role in ("coach", "athlete"), "coach": target_role == "athlete"}.get(actor or "", False)


def may_decide_request(actor: Optional[str], audience: str, request_role: str) -> bool:
    """Mirrors catch_club.may_decide_request. A coach candidate is vetted by owner/admin; in a junior club an athlete is admitted
    by a coach or by the owner (who counts as a coach there, session 27 follow-up), not by an admin, elsewhere by any staff."""
    if request_role == "coach":
        return actor in ADMIN_ROLES
    if audience == "junior":
        return actor in JUNIOR_COACH_ROLES
    return actor in STAFF_ROLES


def may_publish(actor: Optional[str], audience: str) -> bool:
    """Mirrors catch_club.may_publish: whether a post by `actor` goes out immediately. In a junior club only a coach's (or the owner's) does."""
    if audience == "junior":
        return actor in JUNIOR_COACH_ROLES
    return actor in STAFF_ROLES


def post_status_for(actor: Optional[str], audience: str) -> str:
    return "published" if may_publish(actor, audience) else "pending"


def may_approve_post(actor: Optional[str], audience: str) -> bool:
    return may_publish(actor, audience)


def may_create_invite(actor: Optional[str], invite_role: str) -> bool:
    """Staff invite athletes; a coach invite is an owner/admin decision."""
    if invite_role == "coach":
        return actor in ADMIN_ROLES
    return actor in STAFF_ROLES


# action -> roles allowed (club-level, not target-dependent; target rules live in the helpers above)
ACTIONS: dict[str, tuple[str, ...]] = {
    "view": ROLES,
    "edit_club": ADMIN_ROLES,
    "edit_logo": ADMIN_ROLES,
    "delete_club": ("owner",),
    "transfer_ownership": ("owner",),
    "set_roles": ADMIN_ROLES,
    "remove_member": STAFF_ROLES,
    "see_requests": STAFF_ROLES,
    "see_audit": STAFF_ROLES,
    "post": STAFF_ROLES,
    "take_down_post": STAFF_ROLES,
    "delete_post": ADMIN_ROLES,
    "hide_result": STAFF_ROLES,
    "join_challenge": ROLES,
    "link_workout": ROLES,
    "share_result": ROLES,
    "report": ROLES,
    "block": ROLES,
    "leave": ("admin", "coach", "athlete"),  # the owner transfers first
}


def can(role: Optional[str], action: str) -> bool:
    return role in ACTIONS.get(action, ())


def capabilities(role: Optional[str], audience: str) -> dict[str, bool]:
    """What the UI may offer this role. The browser holds no permission logic of its own: it renders what the server says."""
    caps = {a: can(role, a) for a in ACTIONS}
    caps.update({
        "publish_directly": may_publish(role, audience),
        "decide_athlete_requests": may_decide_request(role, audience, "athlete"),
        "decide_coach_requests": may_decide_request(role, audience, "coach"),
        "create_athlete_invite": may_create_invite(role, "athlete"),
        "create_coach_invite": may_create_invite(role, "coach"),
    })
    return caps


# ---------------------------------------------------------------- club fields

@dataclass(frozen=True)
class ClubFields:
    name: str
    description: Optional[str]
    location: Optional[str]
    visibility: str
    audience: str
    join_policy: str
    rules: Optional[str]


def _clean(raw: Optional[str], *, multiline: bool = False) -> Optional[str]:
    if raw is None:
        return None
    text = raw.strip() if multiline else " ".join(raw.split())
    if multiline:
        text = "\n".join(" ".join(line.split()) for line in text.splitlines())
        text = re.sub(r"\n{3,}", "\n\n", text)
    if any(ord(c) < 32 and c != "\n" for c in text):
        raise ValueError("text can't contain control characters")
    return text or None


def has_link(text: str) -> bool:
    return bool(lb._URL_RE.search(text))


def validate_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if not (NAME_MIN <= len(name) <= NAME_MAX):
        raise ValueError(f"a club name is {NAME_MIN}-{NAME_MAX} characters")
    if has_link(name) or any(ord(c) < 32 for c in name):
        raise ValueError("a club name can't contain a web address")
    return name


def validate_club_fields(*, name: str, description: Optional[str] = None, location: Optional[str] = None, visibility: str = "private",
                         audience: str = "adult", join_policy: str = "request", rules: Optional[str] = None) -> ClubFields:
    """The same invariants as the clubs table's CHECK constraints, with messages a person can act on."""
    if visibility not in VISIBILITIES:
        raise ValueError("visibility must be public or private")
    if audience not in AUDIENCES:
        raise ValueError("audience must be adult or junior")
    if join_policy not in JOIN_POLICIES:
        raise ValueError("join policy must be open, request or invite")
    if audience == "junior" and (visibility != "private" or join_policy != "request"):
        raise ValueError("a junior club is always private and every new member needs a coach's approval")
    if join_policy == "open" and visibility != "public":
        raise ValueError("only a public club can be open to join")
    description, location, rules = _clean(description, multiline=True), _clean(location), _clean(rules, multiline=True)
    if description and len(description) > DESCRIPTION_MAX:
        raise ValueError(f"the description is at most {DESCRIPTION_MAX} characters")
    if location and (len(location) > LOCATION_MAX or has_link(location)):
        raise ValueError(f"the location is at most {LOCATION_MAX} characters and can't contain a web address")
    if rules and len(rules) > RULES_MAX:
        raise ValueError(f"the club rules are at most {RULES_MAX} characters")
    if audience == "junior" and any(t and has_link(t) for t in (description, location, rules)):
        raise ValueError("a junior club's text can't contain web addresses")
    return ClubFields(validate_name(name), description, location, visibility, audience, join_policy, rules)


def validate_post(title: str, body: str, audience: str) -> tuple[str, str]:
    title = _clean(title) or ""
    body = _clean(body, multiline=True) or ""
    if not (1 <= len(title) <= TITLE_MAX):
        raise ValueError(f"a title is 1-{TITLE_MAX} characters")
    if not (1 <= len(body) <= BODY_MAX):
        raise ValueError(f"a post is 1-{BODY_MAX} characters")
    return title, body


def validate_reason(raw: Optional[str], *, required: bool = True) -> str:
    reason = " ".join((raw or "").split())
    if required and not reason:
        raise ValueError("A reason is required.")
    if len(reason) > REASON_MAX:
        raise ValueError(f"a reason is at most {REASON_MAX} characters")
    return reason


def validate_message(raw: Optional[str]) -> Optional[str]:
    message = _clean(raw)
    if message and (len(message) > MESSAGE_MAX or has_link(message)):
        raise ValueError(f"a message is at most {MESSAGE_MAX} characters and can't contain a web address")
    return message


# ---------------------------------------------------------------- invites

def new_invite_token() -> str:
    return secrets.token_urlsafe(24)


def invite_hash(token: str) -> str:
    return hashlib.sha256((token or "").strip().encode()).hexdigest()


def invite_hash_candidates(token: str) -> list[str]:
    """Session 26's join codes were hashed after upper-casing; migration 0006 kept those hashes as invites, so try both."""
    plain = invite_hash(token)
    legacy = hashlib.sha256((token or "").strip().upper().encode()).hexdigest()
    return [plain] if plain == legacy else [plain, legacy]


def invite_expiry_days(requested: Optional[int]) -> int:
    days = INVITE_DAYS_DEFAULT if requested is None else int(requested)
    if not (1 <= days <= INVITE_DAYS_MAX):
        raise ValueError(f"an invite lasts 1-{INVITE_DAYS_MAX} days")
    return days


def invite_max_uses(requested: Optional[int]) -> Optional[int]:
    if requested is None:
        return None
    n = int(requested)
    if not (1 <= n <= INVITE_MAX_USES_CAP):
        raise ValueError(f"an invite can be used 1-{INVITE_MAX_USES_CAP} times")
    return n


# ---------------------------------------------------------------- who may be in which club

def membership_age_class(role: str, audience: str) -> str:
    """The only age class a member of this role can hold in this audience (the CHECK on club_members)."""
    return "youth" if role == "athlete" and audience == "junior" else "adult"


def may_hold_role(age_class: str, role: str, audience: str) -> Optional[str]:
    """None if a person of `age_class` may hold `role` in a club of `audience`, otherwise the reason they may not."""
    if role not in ROLES:
        return "that role doesn't exist"
    if age_class == membership_age_class(role, audience):
        return None
    if audience == "junior":
        return "a junior club's athletes are young members and its coaches and admins are adults" if age_class == "adult" else "young members can only join a junior club as athletes"
    return "adult clubs are for adults: young members join a junior club by invitation"


# ---------------------------------------------------------------- aggregates

def suppress_small(count: int, values: Iterable[Optional[float]], *, k: int = K_MIN) -> dict:
    """Total and mean over the members who chose to share a number, or None for both if fewer than `k` did. `count` is always safe
    to show: attendance is not a private figure; a figure that could be one person's number is."""
    shared = [v for v in values if v is not None]
    if len(shared) < k:
        return {"count": count, "shared": len(shared), "total": None, "mean": None, "suppressed": True}
    total = float(sum(shared))
    return {"count": count, "shared": len(shared), "total": total, "mean": total / len(shared), "suppressed": False}


def team_summary(sessions: list[dict], participation: list[dict], member_count: int) -> dict:
    """Aggregates over published sessions and who took part. Inputs carry no identities (`session_id`, optional shared numbers only).
    Output has counts and k-suppressed totals — never a per-person row."""
    by_session: dict[int, list[dict]] = {}
    for p in participation:
        by_session.setdefault(p["session_id"], []).append(p)
    per_session = []
    for s in sessions:
        rows = by_session.get(s["id"], [])
        per_session.append({
            "session_id": s["id"], "title": s["title"], "date": s["date"], "participants": len(rows),
            "distance_m": suppress_small(len(rows), (r.get("shared_distance_m") for r in rows)),
            "duration_s": suppress_small(len(rows), (r.get("shared_duration_s") for r in rows)),
        })
    taken = sum(r["participants"] for r in per_session)
    return {
        "sessions": len(sessions), "participations": taken, "members": member_count,
        "mean_participants": round(taken / len(sessions), 1) if sessions else None,
        "attendance_rate": round(taken / (len(sessions) * member_count), 2) if sessions and member_count else None,
        "per_session": per_session,
        "distance_m": suppress_small(taken, (p.get("shared_distance_m") for p in participation)),
        "duration_s": suppress_small(taken, (p.get("shared_duration_s") for p in participation)),
        "note": f"Totals appear only when at least {K_MIN} members chose to share a number. No recovery, sleep, weight or nutrition data is ever included.",
    }
