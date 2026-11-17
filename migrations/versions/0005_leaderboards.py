"""Public leaderboards and verified results (session 26; docs/leaderboards.md).

Two owned tables (the athlete's private consent and per-publication snapshot) with the usual forced RLS, and seven
GLOBAL tables that hold what other signed-in users may see plus the moderation trail. Global tables are reachable only by
the runtime role `catch_api` (granted directly: it is NOINHERIT, so membership in `authenticated` gives it nothing); the
`authenticated` role has no grant on them, so an athlete cannot read another athlete's row, flip their own entry's status,
or edit the audit log. `moderation_events` is append-only: SELECT and INSERT, plus UPDATE on the two person-reference columns only (so account deletion can detach the person); no row is ever deleted or has its decision rewritten.

A new revision rather than an edit of 0002: that revision's table lists are FROZEN (see its docstring).

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TABLES = ("leaderboard_settings", "result_publications")  # owned: owner_id, RLS per owner
GLOBAL = ("public_athletes", "public_entries", "clubs", "club_members", "moderation_events", "result_reports", "appeals")
UID = "(SELECT auth.uid())::text"
TS = "TIMESTAMP WITH TIME ZONE"


def _owned() -> None:
    op.execute(f"""CREATE TABLE catch.leaderboard_settings (
        owner_id VARCHAR NOT NULL,
        opted_in BOOLEAN NOT NULL,
        consent_version INTEGER,
        opted_in_at {TS},
        attested_min_age_at {TS},
        guardian_attested_at {TS},
        date_precision VARCHAR NOT NULL,
        show_age_band BOOLEAN NOT NULL,
        show_weight_class BOOLEAN NOT NULL,
        age_source VARCHAR,
        self_declared_band VARCHAR,
        updated_at {TS} NOT NULL,
        PRIMARY KEY (owner_id),
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")
    op.execute(f"""CREATE TABLE catch.result_publications (
        owner_id VARCHAR NOT NULL,
        id SERIAL NOT NULL,
        entry_id VARCHAR NOT NULL,
        board_key VARCHAR NOT NULL,
        verification VARCHAR NOT NULL,
        source_kind VARCHAR NOT NULL,
        canonical_id INTEGER,
        activity_id INTEGER,
        piece_id INTEGER,
        provider VARCHAR,
        provider_user_id VARCHAR,
        provider_result_id VARCHAR,
        original_date_utc VARCHAR,
        original_timezone VARCHAR,
        value INTEGER NOT NULL,
        source_digest VARCHAR NOT NULL,
        note VARCHAR,
        note_public BOOLEAN NOT NULL,
        show_age_band BOOLEAN NOT NULL,
        show_weight_class BOOLEAN NOT NULL,
        date_precision VARCHAR NOT NULL,
        created_at {TS} NOT NULL,
        withdrawn_at {TS},
        PRIMARY KEY (id),
        CONSTRAINT uq_result_publications_entry UNIQUE (owner_id, entry_id),
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_result_publications_owner_id ON catch.result_publications (owner_id)")
    for t in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO authenticated")
        op.execute(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO authenticated USING (owner_id = {UID})")
        op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO authenticated WITH CHECK (owner_id = {UID})")
        op.execute(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO authenticated USING (owner_id = {UID}) WITH CHECK (owner_id = {UID})")
        op.execute(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO authenticated USING (owner_id = {UID})")


def _global() -> None:
    op.execute(f"""CREATE TABLE catch.public_athletes (
        public_id VARCHAR NOT NULL,
        owner_id VARCHAR NOT NULL,
        handle VARCHAR,
        handle_ci VARCHAR,
        display_mode VARCHAR NOT NULL,
        age_group VARCHAR,
        age_provenance VARCHAR,
        active BOOLEAN NOT NULL,
        created_at {TS} NOT NULL,
        PRIMARY KEY (public_id),
        UNIQUE (owner_id),
        UNIQUE (handle_ci),
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")
    op.execute(f"""CREATE TABLE catch.public_entries (
        entry_id VARCHAR NOT NULL,
        owner_id VARCHAR NOT NULL,
        public_id VARCHAR NOT NULL,
        athlete_key VARCHAR NOT NULL,
        board_key VARCHAR NOT NULL,
        value INTEGER NOT NULL,
        verification VARCHAR NOT NULL,
        status VARCHAR NOT NULL,
        provider VARCHAR,
        provider_user_id VARCHAR,
        provider_result_id VARCHAR,
        age_years INTEGER,
        age_band VARCHAR,
        age_label VARCHAR,
        age_provenance VARCHAR,
        weight_class VARCHAR,
        date_label VARCHAR,
        note VARCHAR,
        tiebreak VARCHAR NOT NULL,
        created_at {TS} NOT NULL,
        PRIMARY KEY (entry_id),
        CONSTRAINT uq_public_entries_provider_result UNIQUE (provider, provider_user_id, provider_result_id),
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE,
        FOREIGN KEY(public_id) REFERENCES catch.public_athletes (public_id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_public_entries_board ON catch.public_entries (board_key, status)")
    op.execute("CREATE INDEX ix_public_entries_owner_id ON catch.public_entries (owner_id)")
    op.execute(f"""CREATE TABLE catch.clubs (
        club_id VARCHAR NOT NULL,
        name VARCHAR NOT NULL,
        name_ci VARCHAR NOT NULL,
        code_hash VARCHAR NOT NULL,
        created_by VARCHAR,
        created_at {TS} NOT NULL,
        PRIMARY KEY (club_id),
        UNIQUE (name_ci),
        UNIQUE (code_hash)
    )""")
    op.execute(f"""CREATE TABLE catch.club_members (
        club_id VARCHAR NOT NULL,
        public_id VARCHAR NOT NULL,
        joined_at {TS} NOT NULL,
        PRIMARY KEY (club_id, public_id),
        FOREIGN KEY(club_id) REFERENCES catch.clubs (club_id) ON DELETE CASCADE,
        FOREIGN KEY(public_id) REFERENCES catch.public_athletes (public_id) ON DELETE CASCADE
    )""")
    op.execute(f"""CREATE TABLE catch.moderation_events (
        id SERIAL NOT NULL,
        entry_id VARCHAR NOT NULL,
        subject_owner_id VARCHAR,
        from_status VARCHAR,
        to_status VARCHAR NOT NULL,
        actor_kind VARCHAR NOT NULL,
        actor_id VARCHAR,
        reason_code VARCHAR NOT NULL,
        reason_text VARCHAR NOT NULL,
        created_at {TS} NOT NULL,
        PRIMARY KEY (id)
    )""")
    op.execute("CREATE INDEX ix_moderation_events_entry_id ON catch.moderation_events (entry_id)")
    op.execute("CREATE INDEX ix_moderation_events_subject_owner_id ON catch.moderation_events (subject_owner_id)")
    op.execute(f"""CREATE TABLE catch.result_reports (
        id SERIAL NOT NULL,
        entry_id VARCHAR NOT NULL,
        reporter_id VARCHAR,
        reason VARCHAR NOT NULL,
        detail VARCHAR,
        status VARCHAR NOT NULL,
        created_at {TS} NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_result_reports_entry_reporter UNIQUE (entry_id, reporter_id)
    )""")
    op.execute("CREATE INDEX ix_result_reports_entry_id ON catch.result_reports (entry_id)")
    op.execute("CREATE INDEX ix_result_reports_reporter_id ON catch.result_reports (reporter_id)")
    op.execute(f"""CREATE TABLE catch.appeals (
        id SERIAL NOT NULL,
        entry_id VARCHAR NOT NULL,
        owner_id VARCHAR NOT NULL,
        text VARCHAR NOT NULL,
        status VARCHAR NOT NULL,
        resolution_text VARCHAR,
        resolved_by VARCHAR,
        created_at {TS} NOT NULL,
        resolved_at {TS},
        PRIMARY KEY (id)
    )""")
    op.execute("CREATE INDEX ix_appeals_entry_id ON catch.appeals (entry_id)")
    op.execute("CREATE INDEX ix_appeals_owner_id ON catch.appeals (owner_id)")

    # catch_api is NOINHERIT: it needs its own schema USAGE and table grants. `authenticated` gets none of these.
    op.execute("GRANT USAGE ON SCHEMA catch TO catch_api")
    for t in GLOBAL:
        op.execute(f"REVOKE ALL ON catch.{t} FROM PUBLIC, anon, authenticated, service_role")
        op.execute(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
        if t == "moderation_events":
            op.execute(f"GRANT SELECT, INSERT ON catch.{t} TO catch_api")
            op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO catch_api USING (true)")
            op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO catch_api WITH CHECK (true)")
            # Account deletion detaches the person from the log. Column-level: nothing a decision says can be rewritten, and no row deleted.
            op.execute(f"GRANT UPDATE (subject_owner_id, actor_id) ON catch.{t} TO catch_api")
            op.execute(f"CREATE POLICY {t}_detach ON catch.{t} FOR UPDATE TO catch_api USING (true) WITH CHECK (true)")
            continue
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO catch_api")
        op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO catch_api USING (true)")
        op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO catch_api WITH CHECK (true)")
        op.execute(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO catch_api USING (true) WITH CHECK (true)")
        op.execute(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO catch_api USING (true)")
    for seq in ("moderation_events_id_seq", "result_reports_id_seq", "appeals_id_seq"):
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE catch.{seq} TO catch_api")


def upgrade() -> None:
    op.execute("ALTER TABLE catch.activities ADD COLUMN c2_user_id VARCHAR")
    op.execute("ALTER TABLE catch.activities ADD COLUMN c2_verified BOOLEAN")
    op.execute("ALTER TABLE catch.activities ADD COLUMN c2_weight_class VARCHAR")
    _owned()
    _global()
    op.execute("GRANT USAGE, SELECT ON SEQUENCE catch.result_publications_id_seq TO authenticated")


def downgrade() -> None:
    # Published results and the moderation log are dropped; the athletes' own results and Concept2 imports are untouched.
    for t in ("appeals", "result_reports", "moderation_events", "club_members", "clubs", "public_entries", "public_athletes", "result_publications", "leaderboard_settings"):
        op.execute(f"DROP TABLE IF EXISTS catch.{t}")
    for c in ("c2_weight_class", "c2_verified", "c2_user_id"):
        op.execute(f"ALTER TABLE catch.activities DROP COLUMN IF EXISTS {c}")
