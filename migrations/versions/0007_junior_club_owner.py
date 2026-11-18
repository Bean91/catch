"""Junior clubs: the owner counts as a coach, and a junior club may have a logo (session 27 follow-up; docs/clubs.md).

Two decisions the operator made after trying a junior club with one adult account:

* In a junior club the OWNER is automatically a coach for the two things only a coach did: admitting a young athlete
  (`may_decide_request`) and posting without waiting for approval (`may_publish`, which also governs who approves a held post).
  An admin is still not a coach. The owner is an adult by the existing CHECK on `club_members`, so no young member can reach
  that power.
* A junior club may have a logo. `ck_clubs_junior_is_private` keeps the visibility and join-policy clauses and drops
  `has_logo = false`. (Web links in a junior club's posts are allowed in code; no schema change.)

Only function bodies and one CHECK change; no table, policy or grant is added, so POLICY_COUNTS is unchanged. 0006 stays as it was
applied. The downgrade restores the strict 0006 bodies and refuses (CHECK violation) if a junior club by then has a logo; clear
`has_logo` on those clubs first.

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_PUBLISH_COACH_ROLES = {"up": "('coach','owner')", "down": "('coach')"}


def _functions(who: str) -> None:
    roles = _PUBLISH_COACH_ROLES[who]
    op.execute(f"""CREATE OR REPLACE FUNCTION catch_club.may_decide_request(cid text, uid text, req_role text) RETURNS boolean
        LANGUAGE sql SECURITY DEFINER STABLE SET search_path = ''
        AS $$ SELECT CASE
            WHEN req_role = 'coach' THEN coalesce(catch_club.role_of(cid, uid) IN ('owner','admin'), false)
            WHEN (SELECT c.audience FROM catch.clubs c WHERE c.club_id = cid) = 'junior' THEN coalesce(catch_club.role_of(cid, uid) IN {roles}, false)
            ELSE catch_club.is_staff(cid, uid) END $$""")
    op.execute(f"""CREATE OR REPLACE FUNCTION catch_club.may_publish(cid text, uid text) RETURNS boolean
        LANGUAGE sql SECURITY DEFINER STABLE SET search_path = ''
        AS $$ SELECT CASE WHEN (SELECT c.audience FROM catch.clubs c WHERE c.club_id = cid) = 'junior' THEN coalesce(catch_club.role_of(cid, uid) IN {roles}, false)
              ELSE catch_club.is_staff(cid, uid) END $$""")


def upgrade() -> None:
    _functions("up")
    op.execute("ALTER TABLE catch.clubs DROP CONSTRAINT ck_clubs_junior_is_private")
    op.execute("ALTER TABLE catch.clubs ADD CONSTRAINT ck_clubs_junior_is_private CHECK (audience = 'adult' OR (visibility = 'private' AND join_policy = 'request'))")


def downgrade() -> None:
    _functions("down")
    op.execute("ALTER TABLE catch.clubs DROP CONSTRAINT ck_clubs_junior_is_private")
    op.execute("ALTER TABLE catch.clubs ADD CONSTRAINT ck_clubs_junior_is_private CHECK (audience = 'adult' OR (visibility = 'private' AND join_policy = 'request' AND has_logo = false))")
