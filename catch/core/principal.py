from __future__ import annotations

"""Session 22 (see PLAN.md, docs/library.md): who is calling, and the one place that decides what
they may see or change.

Catch is a single-athlete install with no user table. A *principal* is derived per request:
the login cookie and any device token without a role are the athlete; a device token created with
`--role coach` is a coach. A caller with no principal at all is the fail-closed `VIEWER` — new
code (the library/technique-note/feedback tools) treats "unknown" as the most restricted reader,
never as the athlete. Every visibility and ownership rule is a function here, so the service
layer, the tool layer and the tests share one code path."""

from dataclasses import dataclass
from typing import Any, Optional

ATHLETE_ROLE = "athlete"
COACH_ROLE = "coach"
VIEWER_ROLE = "viewer"

OWNER_ID = "owner"  # the personal install's only owner; a public deployment never uses this constant

NOTE_VISIBILITIES = ("private", "coach")
FEEDBACK_VISIBILITIES = ("private", "shared")

# A coach-role token reaches nothing but these: sharing sleep/HR/load data with a coach is a
# separate decision this app doesn't model yet, so it's refused rather than defaulted open.
COACH_TOOLS = frozenset(
    {
        "search_workout_library",
        "get_workout_template",
        "get_technique_notes",
        "get_coach_feedback",
        "add_coach_feedback",
    }
)


@dataclass(frozen=True)
class Principal:
    role: str
    id: str
    name: str = ""
    # Whose training record this principal acts on: the athlete's own id, or — for a coach token — the athlete
    # who minted it. Transports set the request's tenant from this, never from anything the caller sends.
    owner_id: str = OWNER_ID

    @property
    def is_athlete(self) -> bool:
        return self.role == ATHLETE_ROLE


ATHLETE = Principal(ATHLETE_ROLE, OWNER_ID, "You")
VIEWER = Principal(VIEWER_ROLE, "viewer", "", "")


def athlete_for(owner_id: str) -> Principal:
    """The athlete principal of one owner (public: the signed-in user; personal: the constant `ATHLETE`)."""
    return ATHLETE if owner_id == OWNER_ID else Principal(ATHLETE_ROLE, owner_id, "You", owner_id)


def coach_principal(key: object, display_name: Optional[str], owner_id: str = OWNER_ID) -> Principal:
    return Principal(COACH_ROLE, f"coach:{key}", (display_name or "").strip() or "Coach", owner_id)


def principal_from_token(
    token_hash: str, role: Optional[str], display_name: Optional[str], owner_id: str = OWNER_ID
) -> Principal:
    """A coach's identity is a prefix of the token's own hash — random, unique per token and never
    reused. Keying it on `ApiToken.id` would be a bug: SQLite hands a deleted newest row's id to
    the next insert, so a freshly minted coach token would inherit a revoked coach's authorship
    (and the right to edit and delete their feedback)."""
    if role == COACH_ROLE:
        return coach_principal(token_hash[:16], display_name, owner_id)
    return athlete_for(owner_id)


def principal_from(ctx: Optional[dict[str, Any]]) -> Principal:
    p = (ctx or {}).get("principal")
    return p if isinstance(p, Principal) else VIEWER


def may_call_tool(principal: Principal, name: str) -> bool:
    if principal.role == ATHLETE_ROLE:
        return True
    if principal.role == COACH_ROLE:
        return name in COACH_TOOLS
    return False


# --- Technique notes: athlete-authored; "coach" visibility is the share flag --------------------


def note_visible(visibility: str, principal: Principal) -> bool:
    if principal.is_athlete:
        return True
    return principal.role == COACH_ROLE and visibility == "coach"


# --- Feedback ---------------------------------------------------------------------------------


def feedback_visible(visibility: str, author_id: str, principal: Principal) -> bool:
    """`private` is the author's alone; `shared` is the athlete plus any coach-role reader."""
    if visibility == "private":
        return principal.id == author_id
    if principal.is_athlete:
        return True
    return principal.role == COACH_ROLE


def is_author(author_id: str, author_role: str, principal: Principal) -> bool:
    return principal.id == author_id and principal.role == author_role


def can_edit_feedback(author_id: str, author_role: str, principal: Principal) -> bool:
    return is_author(author_id, author_role, principal)


def can_respond_to_feedback(visibility: str, author_id: str, principal: Principal) -> bool:
    """Only the athlete (the subject) writes a response, and only on an entry they can see."""
    return principal.is_athlete and feedback_visible(visibility, author_id, principal)
