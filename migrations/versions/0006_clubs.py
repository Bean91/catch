"""Clubs, team training and group challenges (session 27; docs/clubs.md).

Session 26's `clubs`/`club_members` (join code only, keyed by public leaderboard athlete) are reshaped: clubs gain
visibility/audience/join policy/rules/status, members become owner-keyed with a role. Existing rows are migrated, not
dropped: a member's `public_id` maps to their owner id, the creator becomes owner (else the longest-standing member),
the old join code becomes a 30-day revocable invite, and a leaderboard youth member is NOT carried into an (adult)
club — that is recorded in `club_audit` instead.

Fifteen membership-scoped tables plus one owned table (`club_blocks`, the usual per-owner RLS). Unlike session 26's
global tables, the membership-scoped ones ARE granted to `authenticated`, behind policies that call `catch_club.*`
predicates, so another club's rows are unreachable even if a query forgets its WHERE. The predicates are SECURITY DEFINER
(same pattern as `catch_private.resolve_api_token`: the definer reads the forced-RLS tables) and live in their own
schema because 0002 deliberately keeps `catch_private` away from `authenticated`. `catch_api` also gets permissive
policies (the 0005 pattern), used only under `tenant.system_detached()` for account deletion and platform moderation.

A new revision rather than an edit of 0002/0005: those revisions' table lists are FROZEN.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TABLES = ("club_blocks",)  # owned: owner_id, the usual four per-owner policies
GLOBAL = (  # membership-scoped, no owner column of their own (club_profiles/club_members carry one as a key)
    "clubs", "club_profiles", "club_members", "club_member_prefs", "club_invites", "club_join_requests", "club_announcements",
    "club_sessions", "club_session_participation", "club_challenges", "club_challenge_entries", "club_challenge_claims",
    "club_results", "club_logos", "club_reports", "club_audit",
)
NEW_GLOBAL = tuple(t for t in GLOBAL if t not in ("clubs", "club_members"))  # clubs/club_members exist since 0005
UID = "(SELECT auth.uid())::text"
TS = "TIMESTAMP WITH TIME ZONE"
CHECK_AGE = "age_class IN ('adult','youth')"

# ---------------------------------------------------------------------------------------------------------------------
# `authenticated` policies: {table: {command: (USING, WITH CHECK)}}. The helper predicates are defined in _functions().
# ---------------------------------------------------------------------------------------------------------------------
M = "catch_club"
_MEMBER = f"{M}.is_member(club_id, {UID})"
_STAFF = f"{M}.is_staff(club_id, {UID})"
_ADMIN = f"{M}.is_admin(club_id, {UID})"
_PUBLISH_INSERT = lambda who: f"{_STAFF} AND {who} = {UID} AND (status = 'pending' OR (status = 'published' AND {M}.may_publish(club_id, {UID})))"  # noqa: E731
_PUBLISH_UPDATE = f"{_STAFF} AND (status IN ('rejected','hidden','cancelled') OR (status = 'published' AND {M}.may_publish(club_id, {UID})))"
_POST_SELECT = f"{_MEMBER} AND (status = 'published' OR {_STAFF})"
_OWN = f"owner_id = {UID}"

AUTH: dict[str, dict[str, tuple]] = {
    "clubs": {
        "select": (f"{M}.club_visible(club_id, {UID}) OR created_by = {UID}", None),
        "insert": (None, f"created_by = {UID} AND {M}.is_adult({UID})"),
        "update": (f"{M}.is_admin(club_id, {UID})", f"{M}.is_admin(club_id, {UID})"),
        "delete": (f"{M}.role_of(club_id, {UID}) = 'owner'", None),
    },
    "club_profiles": {
        "select": (f"{_OWN} OR {M}.profile_visible(owner_id, {UID})", None),
        "insert": (None, _OWN),
        "update": (_OWN, _OWN),
        "delete": (_OWN, None),
    },
    "club_members": {
        "select": (f"{_OWN} OR ({_MEMBER} AND (status = 'active' OR {_STAFF}))", None),
        "insert": (None, f"{_OWN} AND status = 'active' AND age_class = (SELECT p.age_class FROM catch.club_profiles p WHERE p.owner_id = {UID}) "
                         f"AND ((role = 'owner' AND {M}.can_claim_ownership(club_id, {UID})) OR (role IN ('athlete','coach') AND {M}.join_allowed(club_id, {UID}, role)))"),
        "update": (f"{M}.can_manage_member(club_id, {UID}, owner_id, role)", f"{M}.can_assign_role(club_id, {UID}, role)"),
        "delete": (f"{_OWN} AND role <> 'owner' AND status = 'active'", None),  # leaving; a removal tombstone is not the member's to delete (they'd rejoin an open club)
    },
    "club_member_prefs": {"select": (_OWN, None), "insert": (None, _OWN), "update": (_OWN, _OWN), "delete": (_OWN, None)},
    "club_invites": {
        "select": (_STAFF, None),
        "insert": (None, f"{_STAFF} AND created_by = {UID} AND (role = 'athlete' OR {_ADMIN})"),
        "update": (_STAFF, _STAFF),
    },
    "club_join_requests": {
        "select": (f"{_OWN} OR {_STAFF}", None),
        "insert": (None, f"{_OWN} AND {M}.may_request(club_id, {UID}, role, via_invite_id) "
                         f"AND (status = 'pending' OR (status = 'approved' AND {M}.invite_grants_entry(club_id, via_invite_id, role)))"),
        "update": (f"status = 'pending' AND {M}.may_decide_request(club_id, {UID}, role)", f"status IN ('approved','rejected') AND decided_by = {UID}"),
        "delete": (_OWN, None),
    },
    "club_announcements": {"select": (_POST_SELECT, None), "insert": (None, _PUBLISH_INSERT("author_id")), "update": (_STAFF, _PUBLISH_UPDATE), "delete": (_ADMIN, None)},
    "club_sessions": {"select": (_POST_SELECT, None), "insert": (None, _PUBLISH_INSERT("created_by")), "update": (_STAFF, _PUBLISH_UPDATE), "delete": (_ADMIN, None)},
    "club_challenges": {"select": (_POST_SELECT, None), "insert": (None, _PUBLISH_INSERT("created_by")), "update": (_STAFF, _PUBLISH_UPDATE), "delete": (_ADMIN, None)},
    "club_session_participation": {
        "select": (_MEMBER, None),
        "insert": (None, f"{_OWN} AND EXISTS (SELECT 1 FROM catch.club_sessions s WHERE s.id = session_id AND s.status = 'published')"),
        "update": (_OWN, _OWN),
        "delete": (_OWN, None),
    },
    "club_challenge_entries": {
        "select": (_MEMBER, None),
        "insert": (None, f"{_OWN} AND {M}.challenge_open(challenge_id)"),
        "update": (f"{_OWN} AND {M}.challenge_open(challenge_id)", f"{_OWN} AND {M}.challenge_open(challenge_id)"),
        "delete": (f"{_OWN} AND {M}.challenge_open(challenge_id)", None),
    },
    "club_challenge_claims": {
        "select": (_OWN, None),
        "insert": (None, f"{_OWN} AND {M}.challenge_open(challenge_id)"),
        "delete": (f"{_OWN} AND {M}.challenge_open(challenge_id)", None),
    },
    "club_results": {
        "select": (f"{_OWN} OR ({_MEMBER} AND status = 'active')", None),
        "insert": (None, _OWN),
        "update": (f"{_OWN} OR {_STAFF}", f"{_OWN} OR {_STAFF}"),
        "delete": (f"{_OWN} OR {_ADMIN}", None),
    },
    "club_logos": {"select": (f"{M}.club_visible(club_id, {UID})", None), "insert": (None, _ADMIN), "update": (_ADMIN, _ADMIN), "delete": (_ADMIN, None)},
    "club_reports": {"select": (f"reporter_id = {UID}", None), "insert": (None, f"reporter_id = {UID} AND {M}.club_visible(club_id, {UID})")},
    "club_audit": {"select": (_STAFF, None), "insert": (None, f"actor_id = {UID} AND {_MEMBER}")},
}
# Column-level UPDATE grants where a row-level policy alone can't say "this column, not that one".
UPDATE_COLUMNS = {
    "clubs": "name, name_ci, description, location, visibility, join_policy, rules, has_logo",  # never status (moderators only) or audience
    "club_profiles": "handle, handle_ci, age_band, age_class, guardian_consent_at, updated_at",
    "club_members": "role, status",
    "club_member_prefs": "include_public_results, share_numbers, rules_accepted_at",
    "club_invites": "revoked_at",
    "club_join_requests": "status, decided_by, decision_reason, decided_at",
    "club_announcements": "status, decided_by, decision_reason, decided_at",
    "club_sessions": "status, decided_by, decision_reason",
    "club_challenges": "status, decided_by, decision_reason",
    "club_session_participation": "shared_distance_m, shared_duration_s",
    "club_challenge_entries": "status, value, excused_weeks, updated_at",
    "club_results": "status",
    "club_logos": "content_type, data, updated_at",
}
SEQUENCES = ("club_invites", "club_join_requests", "club_announcements", "club_sessions", "club_challenges", "club_results", "club_reports", "club_audit")
# Policies per table as pg_policies counts them: the authenticated ones plus catch_api's (four; club_audit three).
POLICY_COUNTS = {t: len(AUTH[t]) + (3 if t == "club_audit" else 4) for t in GLOBAL}
POLICY_COUNTS["club_blocks"] = 4


def _create_tables() -> None:
    op.execute(f"""CREATE TABLE catch.club_profiles (
        owner_id VARCHAR NOT NULL, handle VARCHAR NOT NULL, handle_ci VARCHAR NOT NULL, age_band VARCHAR NOT NULL, age_class VARCHAR NOT NULL,
        guardian_consent_at {TS}, created_at {TS} NOT NULL, updated_at {TS} NOT NULL,
        PRIMARY KEY (owner_id), UNIQUE (handle_ci),
        CONSTRAINT ck_club_profiles_age_class CHECK ({CHECK_AGE}),
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")
    op.execute(f"""CREATE TABLE catch.club_members (
        club_id VARCHAR NOT NULL, owner_id VARCHAR NOT NULL, club_audience VARCHAR NOT NULL, role VARCHAR NOT NULL, status VARCHAR NOT NULL,
        age_class VARCHAR NOT NULL, joined_at {TS} NOT NULL,
        PRIMARY KEY (club_id, owner_id),
        CONSTRAINT ck_club_members_role CHECK (role IN ('owner','admin','coach','athlete')),
        CONSTRAINT ck_club_members_status CHECK (status IN ('active','removed')),
        CONSTRAINT ck_club_members_age_class CHECK ({CHECK_AGE}),
        CONSTRAINT ck_club_members_age_matches_audience CHECK ((age_class = 'youth') = (role = 'athlete' AND club_audience = 'junior')),
        FOREIGN KEY(club_id, club_audience) REFERENCES catch.clubs (club_id, audience) ON DELETE CASCADE,
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")
    op.execute("CREATE UNIQUE INDEX uq_club_members_one_owner ON catch.club_members (club_id) WHERE role = 'owner' AND status = 'active'")
    op.execute("CREATE INDEX ix_club_members_owner_id ON catch.club_members (owner_id)")
    op.execute("""CREATE TABLE catch.club_member_prefs (
        club_id VARCHAR NOT NULL, owner_id VARCHAR NOT NULL, include_public_results BOOLEAN NOT NULL, share_numbers BOOLEAN NOT NULL, rules_accepted_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (club_id, owner_id),
        FOREIGN KEY(club_id, owner_id) REFERENCES catch.club_members (club_id, owner_id) ON DELETE CASCADE
    )""")
    op.execute(f"""CREATE TABLE catch.club_invites (
        id SERIAL NOT NULL, club_id VARCHAR NOT NULL, token_hash VARCHAR NOT NULL, role VARCHAR NOT NULL, created_by VARCHAR,
        expires_at {TS} NOT NULL, max_uses INTEGER, revoked_at {TS}, created_at {TS} NOT NULL,
        PRIMARY KEY (id), UNIQUE (token_hash),
        CONSTRAINT ck_club_invites_role CHECK (role IN ('athlete','coach')),
        FOREIGN KEY(club_id) REFERENCES catch.clubs (club_id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_club_invites_club_id ON catch.club_invites (club_id)")
    op.execute(f"""CREATE TABLE catch.club_join_requests (
        id SERIAL NOT NULL, club_id VARCHAR NOT NULL, owner_id VARCHAR NOT NULL, role VARCHAR NOT NULL, message VARCHAR, status VARCHAR NOT NULL,
        via_invite_id INTEGER, decided_by VARCHAR, decision_reason VARCHAR, created_at {TS} NOT NULL, decided_at {TS},
        PRIMARY KEY (id),
        CONSTRAINT ck_club_join_requests_status CHECK (status IN ('pending','approved','rejected')),
        CONSTRAINT ck_club_join_requests_role CHECK (role IN ('athlete','coach')),
        FOREIGN KEY(club_id) REFERENCES catch.clubs (club_id) ON DELETE CASCADE,
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE,
        FOREIGN KEY(via_invite_id) REFERENCES catch.club_invites (id) ON DELETE SET NULL
    )""")
    op.execute("CREATE INDEX ix_club_join_requests_club_id ON catch.club_join_requests (club_id)")
    op.execute("CREATE INDEX ix_club_join_requests_owner_id ON catch.club_join_requests (owner_id)")
    op.execute("CREATE INDEX ix_club_join_requests_via_invite_id ON catch.club_join_requests (via_invite_id)")
    op.execute("CREATE UNIQUE INDEX uq_club_join_requests_pending ON catch.club_join_requests (club_id, owner_id) WHERE status = 'pending'")
    op.execute(f"""CREATE TABLE catch.club_announcements (
        id SERIAL NOT NULL, club_id VARCHAR NOT NULL, author_id VARCHAR, title VARCHAR NOT NULL, body VARCHAR NOT NULL, status VARCHAR NOT NULL,
        decided_by VARCHAR, decision_reason VARCHAR, created_at {TS} NOT NULL, decided_at {TS},
        PRIMARY KEY (id), CONSTRAINT uq_club_announcements_id_club UNIQUE (id, club_id),
        CONSTRAINT ck_club_announcements_status CHECK (status IN ('pending','published','rejected','hidden')),
        FOREIGN KEY(club_id) REFERENCES catch.clubs (club_id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_club_announcements_club_id ON catch.club_announcements (club_id)")
    op.execute(f"""CREATE TABLE catch.club_sessions (
        id SERIAL NOT NULL, club_id VARCHAR NOT NULL, created_by VARCHAR, title VARCHAR NOT NULL, session_type VARCHAR NOT NULL, date DATE NOT NULL,
        start_time VARCHAR, duration_min INTEGER, distance_m INTEGER, description VARCHAR, status VARCHAR NOT NULL, decided_by VARCHAR,
        decision_reason VARCHAR, created_at {TS} NOT NULL,
        PRIMARY KEY (id), CONSTRAINT uq_club_sessions_id_club UNIQUE (id, club_id),
        CONSTRAINT ck_club_sessions_status CHECK (status IN ('pending','published','cancelled','rejected')),
        FOREIGN KEY(club_id) REFERENCES catch.clubs (club_id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_club_sessions_club_id ON catch.club_sessions (club_id)")
    op.execute(f"""CREATE TABLE catch.club_session_participation (
        session_id INTEGER NOT NULL, owner_id VARCHAR NOT NULL, club_id VARCHAR NOT NULL, shared_distance_m INTEGER, shared_duration_s INTEGER, created_at {TS} NOT NULL,
        PRIMARY KEY (session_id, owner_id),
        FOREIGN KEY(session_id, club_id) REFERENCES catch.club_sessions (id, club_id) ON DELETE CASCADE,
        FOREIGN KEY(club_id, owner_id) REFERENCES catch.club_members (club_id, owner_id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_club_session_participation_club_id ON catch.club_session_participation (club_id)")
    op.execute(f"""CREATE TABLE catch.club_challenges (
        id SERIAL NOT NULL, club_id VARCHAR NOT NULL, created_by VARCHAR, title VARCHAR NOT NULL, description VARCHAR, metric VARCHAR NOT NULL, sport VARCHAR NOT NULL,
        start_date DATE NOT NULL, end_date DATE NOT NULL, goal INTEGER, target_per_week INTEGER, day_cap_m INTEGER, day_cap_s INTEGER,
        min_session_s INTEGER NOT NULL, status VARCHAR NOT NULL, decided_by VARCHAR, decision_reason VARCHAR, created_at {TS} NOT NULL,
        PRIMARY KEY (id), CONSTRAINT uq_club_challenges_id_club UNIQUE (id, club_id),
        CONSTRAINT ck_club_challenges_metric CHECK (metric IN ('distance','time','sessions','tests','consistency')),
        CONSTRAINT ck_club_challenges_sport CHECK (sport IN ('rowing','any')),
        CONSTRAINT ck_club_challenges_status CHECK (status IN ('pending','active','cancelled','rejected')),
        CONSTRAINT ck_club_challenges_dates CHECK (start_date <= end_date),
        CONSTRAINT ck_club_challenges_volume_has_cap CHECK (metric NOT IN ('distance','time') OR goal IS NOT NULL),
        FOREIGN KEY(club_id) REFERENCES catch.clubs (club_id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_club_challenges_club_id ON catch.club_challenges (club_id)")
    op.execute(f"""CREATE TABLE catch.club_challenge_entries (
        challenge_id INTEGER NOT NULL, owner_id VARCHAR NOT NULL, club_id VARCHAR NOT NULL, status VARCHAR NOT NULL, value INTEGER NOT NULL,
        excused_weeks VARCHAR, joined_at {TS} NOT NULL, updated_at {TS} NOT NULL,
        PRIMARY KEY (challenge_id, owner_id),
        CONSTRAINT ck_club_challenge_entries_status CHECK (status IN ('joined','left')),
        FOREIGN KEY(challenge_id, club_id) REFERENCES catch.club_challenges (id, club_id) ON DELETE CASCADE,
        FOREIGN KEY(club_id, owner_id) REFERENCES catch.club_members (club_id, owner_id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_club_challenge_entries_club_id ON catch.club_challenge_entries (club_id)")
    op.execute("""CREATE TABLE catch.club_challenge_claims (
        challenge_id INTEGER NOT NULL, activity_key VARCHAR NOT NULL, owner_id VARCHAR NOT NULL,
        PRIMARY KEY (challenge_id, activity_key),
        FOREIGN KEY(challenge_id) REFERENCES catch.club_challenges (id) ON DELETE CASCADE,
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_club_challenge_claims_owner_id ON catch.club_challenge_claims (owner_id)")
    op.execute(f"""CREATE TABLE catch.club_results (
        id SERIAL NOT NULL, club_id VARCHAR NOT NULL, owner_id VARCHAR NOT NULL, board_key VARCHAR NOT NULL, value INTEGER NOT NULL, verification VARCHAR NOT NULL,
        source_key VARCHAR NOT NULL, note VARCHAR, status VARCHAR NOT NULL, created_at {TS} NOT NULL,
        PRIMARY KEY (id), CONSTRAINT uq_club_results_source UNIQUE (club_id, source_key),
        CONSTRAINT ck_club_results_status CHECK (status IN ('active','hidden')),
        FOREIGN KEY(club_id, owner_id) REFERENCES catch.club_members (club_id, owner_id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_club_results_club_id ON catch.club_results (club_id)")
    op.execute("CREATE INDEX ix_club_results_owner_id ON catch.club_results (owner_id)")
    op.execute(f"""CREATE TABLE catch.club_logos (
        club_id VARCHAR NOT NULL, content_type VARCHAR NOT NULL, data BYTEA NOT NULL, updated_at {TS} NOT NULL,
        PRIMARY KEY (club_id), CONSTRAINT ck_club_logos_size CHECK (length(data) <= 262144),
        FOREIGN KEY(club_id) REFERENCES catch.clubs (club_id) ON DELETE CASCADE
    )""")
    op.execute(f"""CREATE TABLE catch.club_reports (
        id SERIAL NOT NULL, club_id VARCHAR NOT NULL, target_type VARCHAR NOT NULL, target_id VARCHAR NOT NULL, reporter_id VARCHAR,
        reason VARCHAR NOT NULL, detail VARCHAR, status VARCHAR NOT NULL, created_at {TS} NOT NULL,
        PRIMARY KEY (id), CONSTRAINT uq_club_reports_target_reporter UNIQUE (target_type, target_id, reporter_id),
        CONSTRAINT ck_club_reports_target CHECK (target_type IN ('club','announcement','member','challenge')),
        CONSTRAINT ck_club_reports_status CHECK (status IN ('open','actioned','dismissed')),
        FOREIGN KEY(club_id) REFERENCES catch.clubs (club_id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_club_reports_club_id ON catch.club_reports (club_id)")
    op.execute("CREATE INDEX ix_club_reports_reporter_id ON catch.club_reports (reporter_id)")
    op.execute(f"""CREATE TABLE catch.club_audit (
        id SERIAL NOT NULL, club_id VARCHAR NOT NULL, actor_id VARCHAR, actor_kind VARCHAR NOT NULL, action VARCHAR NOT NULL, target_type VARCHAR, target_id VARCHAR,
        subject_owner_id VARCHAR, reason_text VARCHAR NOT NULL, created_at {TS} NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_club_audit_actor_kind CHECK (actor_kind IN ('member','staff','moderator','system'))
    )""")
    op.execute("CREATE INDEX ix_club_audit_club_id ON catch.club_audit (club_id)")
    op.execute("CREATE INDEX ix_club_audit_subject_owner_id ON catch.club_audit (subject_owner_id)")
    op.execute(f"""CREATE TABLE catch.club_blocks (
        owner_id VARCHAR NOT NULL, blocked_owner_id VARCHAR NOT NULL, created_at {TS} NOT NULL,
        PRIMARY KEY (owner_id, blocked_owner_id),
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")


def _reshape_clubs() -> None:
    # 1. keep what the old members table knew, then drop it (its shape can't be altered into the new one).
    op.execute("""CREATE TABLE catch._club_members_old AS
        SELECT m.club_id, a.owner_id, m.joined_at, a.age_group FROM catch.club_members m JOIN catch.public_athletes a ON a.public_id = m.public_id""")
    op.execute("DROP TABLE catch.club_members")
    # 2. clubs: new columns (existing clubs are private adult clubs where a valid invite joins directly, as the old code did).
    op.execute("ALTER TABLE catch.clubs ADD COLUMN description VARCHAR")
    op.execute("ALTER TABLE catch.clubs ADD COLUMN location VARCHAR")
    op.execute("ALTER TABLE catch.clubs ADD COLUMN visibility VARCHAR NOT NULL DEFAULT 'private'")
    op.execute("ALTER TABLE catch.clubs ADD COLUMN audience VARCHAR NOT NULL DEFAULT 'adult'")
    op.execute("ALTER TABLE catch.clubs ADD COLUMN join_policy VARCHAR NOT NULL DEFAULT 'invite'")
    op.execute("ALTER TABLE catch.clubs ADD COLUMN rules VARCHAR")
    op.execute("ALTER TABLE catch.clubs ADD COLUMN status VARCHAR NOT NULL DEFAULT 'active'")
    op.execute("ALTER TABLE catch.clubs ADD COLUMN has_logo BOOLEAN NOT NULL DEFAULT false")
    for c in ("visibility", "audience", "join_policy", "status", "has_logo"):
        op.execute(f"ALTER TABLE catch.clubs ALTER COLUMN {c} DROP DEFAULT")
    op.execute("ALTER TABLE catch.clubs ADD CONSTRAINT uq_clubs_id_audience UNIQUE (club_id, audience)")
    op.execute("ALTER TABLE catch.clubs ADD CONSTRAINT ck_clubs_visibility CHECK (visibility IN ('public','private'))")
    op.execute("ALTER TABLE catch.clubs ADD CONSTRAINT ck_clubs_audience CHECK (audience IN ('adult','junior'))")
    op.execute("ALTER TABLE catch.clubs ADD CONSTRAINT ck_clubs_join_policy CHECK (join_policy IN ('open','request','invite'))")
    op.execute("ALTER TABLE catch.clubs ADD CONSTRAINT ck_clubs_status CHECK (status IN ('active','suspended'))")
    op.execute("ALTER TABLE catch.clubs ADD CONSTRAINT ck_clubs_junior_is_private CHECK (audience = 'adult' OR (visibility = 'private' AND join_policy = 'request' AND has_logo = false))")
    op.execute("ALTER TABLE catch.clubs ADD CONSTRAINT ck_clubs_open_is_public CHECK (join_policy <> 'open' OR visibility = 'public')")


def _backfill() -> None:
    youth = "o.age_group ~ '^U[0-9]+$'"
    op.execute(f"""INSERT INTO catch.club_audit (club_id, actor_kind, action, subject_owner_id, reason_text, created_at)
        SELECT o.club_id, 'system', 'migration_member_not_carried', o.owner_id,
               'Not carried over from the old club: a leaderboard age band under 19 cannot be in an adult club. Join a junior club by invitation instead.', now()
        FROM catch._club_members_old o WHERE {youth}""")
    op.execute(f"""INSERT INTO catch.club_members (club_id, owner_id, club_audience, role, status, age_class, joined_at)
        SELECT o.club_id, o.owner_id, 'adult', 'athlete', 'active', 'adult', o.joined_at FROM catch._club_members_old o WHERE coalesce(NOT ({youth}), true)""")  # an unknown age band (NULL) is carried over as an adult: NOT NULL would be NULL
    # Owner: the creator if still a member, otherwise the longest-standing member.
    op.execute("""UPDATE catch.club_members m SET role = 'owner' FROM catch.clubs c WHERE c.club_id = m.club_id AND m.owner_id = c.created_by""")
    op.execute("""UPDATE catch.club_members m SET role = 'owner' WHERE NOT EXISTS (SELECT 1 FROM catch.club_members x WHERE x.club_id = m.club_id AND x.role = 'owner')
        AND m.owner_id = (SELECT y.owner_id FROM catch.club_members y WHERE y.club_id = m.club_id ORDER BY y.joined_at, y.owner_id LIMIT 1)""")
    # The old join code lives on as a 30-day revocable invite (its hash is the sha256 of the upper-cased code, as before).
    op.execute("""INSERT INTO catch.club_invites (club_id, token_hash, role, created_by, expires_at, created_at)
        SELECT c.club_id, c.code_hash, 'athlete', (SELECT m.owner_id FROM catch.club_members m WHERE m.club_id = c.club_id AND m.role = 'owner'),
               now() + interval '30 days', now()
        FROM catch.clubs c WHERE EXISTS (SELECT 1 FROM catch.club_members m WHERE m.club_id = c.club_id)""")
    op.execute("ALTER TABLE catch.clubs DROP COLUMN code_hash")
    op.execute("DELETE FROM catch.clubs c WHERE NOT EXISTS (SELECT 1 FROM catch.club_members m WHERE m.club_id = c.club_id)")
    op.execute("DROP TABLE catch._club_members_old")


def _functions() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS catch_club")
    op.execute("REVOKE ALL ON SCHEMA catch_club FROM PUBLIC, anon")
    op.execute("GRANT USAGE ON SCHEMA catch_club TO authenticated, catch_api")

    def fn(signature: str, returns: str, body: str, *, stable: bool = True) -> None:
        name = signature.split("(")[0]
        args = signature[signature.index("("):]
        op.execute(f"""CREATE OR REPLACE FUNCTION catch_club.{name}{args} RETURNS {returns}
            LANGUAGE sql SECURITY DEFINER {'STABLE' if stable else 'VOLATILE'} SET search_path = ''
            AS $$ {body} $$""")
        types = ", ".join(p.strip().split(" ", 1)[1] for p in args.strip("()").split(",") if p.strip())
        op.execute(f"REVOKE ALL ON FUNCTION catch_club.{name}({types}) FROM PUBLIC, anon")
        op.execute(f"GRANT EXECUTE ON FUNCTION catch_club.{name}({types}) TO authenticated, catch_api")

    fn("role_of(cid text, uid text)", "text", "SELECT m.role FROM catch.club_members m WHERE m.club_id = cid AND m.owner_id = uid AND m.status = 'active'")
    fn("is_member(cid text, uid text)", "boolean", "SELECT catch_club.role_of(cid, uid) IS NOT NULL")
    fn("is_staff(cid text, uid text)", "boolean", "SELECT coalesce(catch_club.role_of(cid, uid) IN ('owner','admin','coach'), false)")
    fn("is_admin(cid text, uid text)", "boolean", "SELECT coalesce(catch_club.role_of(cid, uid) IN ('owner','admin'), false)")
    fn("is_adult(uid text)", "boolean", "SELECT EXISTS (SELECT 1 FROM catch.club_profiles p WHERE p.owner_id = uid AND p.age_class = 'adult')")
    fn("club_visible(cid text, uid text)", "boolean",
       """SELECT EXISTS (SELECT 1 FROM catch.clubs c WHERE c.club_id = cid AND (
              (c.visibility = 'public' AND c.status = 'active' AND c.audience = 'adult')
              OR EXISTS (SELECT 1 FROM catch.club_members m WHERE m.club_id = c.club_id AND m.owner_id = uid AND m.status = 'active')))""")
    fn("profile_visible(target text, viewer text)", "boolean",
       """SELECT EXISTS (SELECT 1 FROM catch.club_members a JOIN catch.club_members b ON a.club_id = b.club_id
                         WHERE a.owner_id = target AND b.owner_id = viewer AND a.status = 'active' AND b.status = 'active')
              OR EXISTS (SELECT 1 FROM catch.club_join_requests r JOIN catch.club_members s ON s.club_id = r.club_id
                         WHERE r.owner_id = target AND r.status = 'pending' AND s.owner_id = viewer AND s.status = 'active' AND s.role IN ('owner','admin','coach'))""")
    fn("invite_valid(inv integer, cid text, req_role text)", "boolean",
       """SELECT EXISTS (SELECT 1 FROM catch.club_invites i WHERE i.id = inv AND i.club_id = cid AND i.role = req_role AND i.revoked_at IS NULL AND i.expires_at > now()
              AND (i.max_uses IS NULL OR (SELECT count(*) FROM catch.club_join_requests r WHERE r.via_invite_id = i.id) < i.max_uses))""")
    fn("invite_grants_entry(cid text, inv integer, req_role text)", "boolean",
       """SELECT catch_club.invite_valid(inv, cid, req_role) AND EXISTS (SELECT 1 FROM catch.clubs c WHERE c.club_id = cid AND c.join_policy = 'invite' AND c.audience = 'adult')""")
    # A person may ask to join only if clubs say their declared age fits, they aren't already in (or removed from) it, and — for a private club — they hold a valid invite.
    fn("may_request(cid text, uid text, req_role text, inv integer)", "boolean",
       """SELECT EXISTS (
            SELECT 1 FROM catch.clubs c JOIN catch.club_profiles p ON p.owner_id = uid
            WHERE c.club_id = cid AND c.status = 'active'
              AND NOT EXISTS (SELECT 1 FROM catch.club_members m WHERE m.club_id = cid AND m.owner_id = uid)
              AND ((c.audience = 'junior' AND ((req_role = 'athlete' AND p.age_class = 'youth') OR (req_role = 'coach' AND p.age_class = 'adult')))
                   OR (c.audience = 'adult' AND p.age_class = 'adult'))
              AND (c.visibility = 'public' OR (inv IS NOT NULL AND catch_club.invite_valid(inv, cid, req_role))))""")
    fn("join_allowed(cid text, uid text, new_role text)", "boolean",
       """SELECT EXISTS (SELECT 1 FROM catch.clubs c WHERE c.club_id = cid AND c.status = 'active'
              AND NOT EXISTS (SELECT 1 FROM catch.club_members m WHERE m.club_id = cid AND m.owner_id = uid)
              AND ((new_role = 'athlete' AND c.join_policy = 'open' AND c.visibility = 'public' AND c.audience = 'adult')
                   OR EXISTS (SELECT 1 FROM catch.club_join_requests r WHERE r.club_id = cid AND r.owner_id = uid AND r.status = 'approved' AND r.role = new_role
                              AND coalesce(r.decided_at, r.created_at) > now() - interval '14 days')))""")
    fn("can_claim_ownership(cid text, uid text)", "boolean",
       "SELECT EXISTS (SELECT 1 FROM catch.clubs c WHERE c.club_id = cid AND c.created_by = uid) AND NOT EXISTS (SELECT 1 FROM catch.club_members m WHERE m.club_id = cid)")
    fn("may_decide_request(cid text, uid text, req_role text)", "boolean",
       """SELECT CASE
            WHEN req_role = 'coach' THEN coalesce(catch_club.role_of(cid, uid) IN ('owner','admin'), false)
            WHEN (SELECT c.audience FROM catch.clubs c WHERE c.club_id = cid) = 'junior' THEN coalesce(catch_club.role_of(cid, uid) = 'coach', false)
            ELSE catch_club.is_staff(cid, uid) END""")
    fn("may_publish(cid text, uid text)", "boolean",
       """SELECT CASE WHEN (SELECT c.audience FROM catch.clubs c WHERE c.club_id = cid) = 'junior' THEN coalesce(catch_club.role_of(cid, uid) = 'coach', false)
              ELSE catch_club.is_staff(cid, uid) END""")
    fn("can_manage_member(cid text, uid text, target text, target_role text)", "boolean",
       """SELECT target <> uid AND CASE catch_club.role_of(cid, uid)
              WHEN 'owner' THEN target_role <> 'owner' WHEN 'admin' THEN target_role IN ('coach','athlete') WHEN 'coach' THEN target_role = 'athlete' ELSE false END""")
    fn("can_assign_role(cid text, uid text, new_role text)", "boolean",
       """SELECT CASE catch_club.role_of(cid, uid)
              WHEN 'owner' THEN new_role IN ('admin','coach','athlete') WHEN 'admin' THEN new_role IN ('coach','athlete') WHEN 'coach' THEN new_role = 'athlete' ELSE false END""")
    fn("challenge_open(chid integer)", "boolean",
       "SELECT EXISTS (SELECT 1 FROM catch.club_challenges c WHERE c.id = chid AND c.status = 'active' AND current_date <= c.end_date + 2)")
    # Discovery needs a count, never a list.
    fn("member_count(cid text)", "integer", "SELECT count(*)::integer FROM catch.club_members m WHERE m.club_id = cid AND m.status = 'active'")
    # A person holding an invite link may read just enough about the club to decide, before anything is shared with them.
    op.execute("""CREATE OR REPLACE FUNCTION catch_club.invite_preview(token_hash_in text)
        RETURNS TABLE (invite_id integer, club_id text, name text, description text, audience text, visibility text, join_policy text, rules text, role text)
        LANGUAGE sql SECURITY DEFINER STABLE SET search_path = ''
        AS $$ SELECT i.id, c.club_id, c.name, c.description, c.audience, c.visibility, c.join_policy, c.rules, i.role
              FROM catch.club_invites i JOIN catch.clubs c ON c.club_id = i.club_id
              WHERE i.token_hash = token_hash_in AND i.revoked_at IS NULL AND i.expires_at > now() AND c.status = 'active'
                AND (i.max_uses IS NULL OR (SELECT count(*) FROM catch.club_join_requests r WHERE r.via_invite_id = i.id) < i.max_uses) LIMIT 1 $$""")
    op.execute("REVOKE ALL ON FUNCTION catch_club.invite_preview(text) FROM PUBLIC, anon")
    op.execute("GRANT EXECUTE ON FUNCTION catch_club.invite_preview(text) TO authenticated, catch_api")
    # Handing the club to someone else: demote first, then promote, because the one-owner index is not deferrable.
    op.execute("""CREATE OR REPLACE FUNCTION catch_club.transfer_ownership(cid text, new_owner text) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = ''
        AS $$ DECLARE me text := (SELECT auth.uid())::text;
        BEGIN
            IF catch_club.role_of(cid, me) IS DISTINCT FROM 'owner' THEN RAISE EXCEPTION 'only the owner can transfer a club' USING ERRCODE = '42501'; END IF;
            IF new_owner = me OR catch_club.role_of(cid, new_owner) IS NULL THEN RAISE EXCEPTION 'the new owner must be another active member' USING ERRCODE = '22023'; END IF;
            UPDATE catch.club_members SET role = 'admin' WHERE club_id = cid AND owner_id = me;
            UPDATE catch.club_members SET role = 'owner' WHERE club_id = cid AND owner_id = new_owner;
        END $$""")
    op.execute("REVOKE ALL ON FUNCTION catch_club.transfer_ownership(text, text) FROM PUBLIC, anon")
    op.execute("GRANT EXECUTE ON FUNCTION catch_club.transfer_ownership(text, text) TO authenticated, catch_api")


def _policies() -> None:
    op.execute("GRANT USAGE ON SCHEMA catch TO catch_api")  # idempotent; 0005 granted it
    for t in GLOBAL:
        # clubs already had 0005's catch_api policies and an empty `authenticated` grant: start from a clean slate for both.
        for cmd in ("select", "insert", "update", "delete", "detach"):
            op.execute(f"DROP POLICY IF EXISTS {t}_{cmd} ON catch.{t}")
        op.execute(f"REVOKE ALL ON catch.{t} FROM PUBLIC, anon, authenticated, service_role")
        op.execute(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
        pol = AUTH[t]
        grants = {"select": "SELECT", "insert": "INSERT", "delete": "DELETE"}
        for cmd, (using, check) in pol.items():
            if cmd in grants:
                op.execute(f"GRANT {grants[cmd]} ON catch.{t} TO authenticated")
            elif cmd == "update":
                op.execute(f"GRANT UPDATE ({UPDATE_COLUMNS[t]}) ON catch.{t} TO authenticated")
            clauses = (f" USING ({using})" if using else "") + (f" WITH CHECK ({check})" if check else "")
            op.execute(f"CREATE POLICY {t}_{cmd}_auth ON catch.{t} FOR {cmd.upper()} TO authenticated{clauses}")
        if t == "club_audit":
            op.execute(f"GRANT SELECT, INSERT ON catch.{t} TO catch_api")
            op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO catch_api USING (true)")
            op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO catch_api WITH CHECK (true)")
            op.execute(f"GRANT UPDATE (subject_owner_id, actor_id) ON catch.{t} TO catch_api")  # detach a deleted person; nothing else is rewritable
            op.execute(f"CREATE POLICY {t}_detach ON catch.{t} FOR UPDATE TO catch_api USING (true) WITH CHECK (true)")
            continue
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO catch_api")
        for cmd, clause in (("select", "USING (true)"), ("insert", "WITH CHECK (true)"), ("update", "USING (true) WITH CHECK (true)"), ("delete", "USING (true)")):
            op.execute(f"CREATE POLICY {t}_{cmd} ON catch.{t} FOR {cmd.upper()} TO catch_api {clause}")
    for s in SEQUENCES:
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE catch.{s}_id_seq TO authenticated, catch_api")
    for t in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO authenticated")
        op.execute(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO authenticated USING (owner_id = {UID})")
        op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO authenticated WITH CHECK (owner_id = {UID})")
        op.execute(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO authenticated USING (owner_id = {UID}) WITH CHECK (owner_id = {UID})")
        op.execute(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO authenticated USING (owner_id = {UID})")


def upgrade() -> None:
    _reshape_clubs()
    _create_tables()
    _backfill()
    _functions()
    _policies()


def downgrade() -> None:
    # Everything new is dropped and 0005's empty-shaped club tables are restored (clubs and members are NOT carried back: the
    # old shape keyed membership by public athlete and had no roles, so there is nothing faithful to restore).
    op.execute("DROP SCHEMA IF EXISTS catch_club CASCADE")
    for t in ("club_blocks", "club_audit", "club_reports", "club_logos", "club_results", "club_challenge_claims", "club_challenge_entries",
              "club_challenges", "club_session_participation", "club_sessions", "club_announcements", "club_join_requests", "club_invites",
              "club_member_prefs", "club_members", "club_profiles"):
        op.execute(f"DROP TABLE IF EXISTS catch.{t}")
    op.execute("DROP TABLE IF EXISTS catch.clubs")
    op.execute("""CREATE TABLE catch.clubs (
        club_id VARCHAR NOT NULL, name VARCHAR NOT NULL, name_ci VARCHAR NOT NULL, code_hash VARCHAR NOT NULL, created_by VARCHAR,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL, PRIMARY KEY (club_id), UNIQUE (name_ci), UNIQUE (code_hash))""")
    op.execute("""CREATE TABLE catch.club_members (
        club_id VARCHAR NOT NULL, public_id VARCHAR NOT NULL, joined_at TIMESTAMP WITH TIME ZONE NOT NULL, PRIMARY KEY (club_id, public_id),
        FOREIGN KEY(club_id) REFERENCES catch.clubs (club_id) ON DELETE CASCADE,
        FOREIGN KEY(public_id) REFERENCES catch.public_athletes (public_id) ON DELETE CASCADE)""")
    for t in ("clubs", "club_members"):
        op.execute(f"REVOKE ALL ON catch.{t} FROM PUBLIC, anon, authenticated, service_role")
        op.execute(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO catch_api")
        for cmd, clause in (("select", "USING (true)"), ("insert", "WITH CHECK (true)"), ("update", "USING (true) WITH CHECK (true)"), ("delete", "USING (true)")):
            op.execute(f"CREATE POLICY {t}_{cmd} ON catch.{t} FOR {cmd.upper()} TO catch_api {clause}")
