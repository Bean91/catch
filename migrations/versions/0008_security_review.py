"""Session 28 (security and privacy review): new tables and columns.

`deleted_accounts` is GLOBAL: the tombstone account deletion writes just before the auth user is removed, so a token that is
still inside its signature lifetime can't re-create the profile. Like the leaderboard globals it is reachable only by the
runtime role `catch_api`; `authenticated` has no grant, so no user can read or write it.

Later layers of the session append their tables to this same revision (it has not been applied anywhere yet).

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TABLES = ("tool_call_log", "ai_sharing_settings")  # owned (owner_id + forced RLS)
UID = "(SELECT auth.uid())::text"
GLOBAL = ("deleted_accounts", "account_restrictions", "moderation_actions", "moderator_access_log")  # catch_api only
APPEND_ONLY = ("moderation_actions", "moderator_access_log")  # SELECT + INSERT only
TS = "TIMESTAMP WITH TIME ZONE"
POLICY_COUNT_DELTAS = {"club_audit": 1}
POLICY_COUNT_ABSOLUTE = {"moderation_actions": 2, "moderator_access_log": 2}  # append-only: select + insert  # tests/pg/test_migrations.py adds these to the counts it derives from earlier revisions
AUDIT_RETENTION = "24 months"


def _global_grants(t: str) -> None:
    op.execute(f"REVOKE ALL ON catch.{t} FROM PUBLIC, anon, authenticated, service_role")
    op.execute(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
    if t in APPEND_ONLY:
        op.execute(f"GRANT SELECT, INSERT ON catch.{t} TO catch_api")
        op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO catch_api USING (true)")
        op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO catch_api WITH CHECK (true)")
        return
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO catch_api")
    op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO catch_api USING (true)")
    op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO catch_api WITH CHECK (true)")
    op.execute(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO catch_api USING (true) WITH CHECK (true)")
    op.execute(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO catch_api USING (true)")


def _owned(t: str) -> None:
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO authenticated")
    op.execute(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO authenticated USING (owner_id = {UID})")
    op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO authenticated WITH CHECK (owner_id = {UID})")
    op.execute(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO authenticated USING (owner_id = {UID}) WITH CHECK (owner_id = {UID})")
    op.execute(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO authenticated USING (owner_id = {UID})")


def upgrade() -> None:
    op.execute("ALTER TABLE catch.api_tokens ADD COLUMN scope VARCHAR")
    op.execute(f"ALTER TABLE catch.api_tokens ADD COLUMN expires_at {TS}")
    op.execute(f"""CREATE TABLE catch.tool_call_log (
        owner_id VARCHAR NOT NULL,
        id SERIAL NOT NULL,
        tool VARCHAR NOT NULL,
        via VARCHAR NOT NULL,
        principal_kind VARCHAR NOT NULL,
        is_write BOOLEAN NOT NULL,
        confirmed BOOLEAN NOT NULL,
        outcome VARCHAR NOT NULL,
        args_hash VARCHAR,
        created_at {TS} NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_tool_call_log_owner_id ON catch.tool_call_log (owner_id)")
    op.execute(f"""CREATE TABLE catch.ai_sharing_settings (
        owner_id VARCHAR NOT NULL,
        consent_version INTEGER NOT NULL,
        consented_at {TS},
        categories_json VARCHAR NOT NULL,
        age_band VARCHAR,
        guardian_ack_at {TS},
        updated_at {TS} NOT NULL,
        PRIMARY KEY (owner_id),
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE catch.tool_call_log_id_seq TO authenticated")
    # A device token resolves to its owner, role, scope and expiry before any owner is known (same SECURITY DEFINER shape as 0002).
    op.execute("DROP FUNCTION IF EXISTS catch_private.resolve_api_token(text)")
    op.execute("""CREATE FUNCTION catch_private.resolve_api_token(token_hash_in text)
        RETURNS TABLE (token_id integer, owner_id text, role text, display_name text, scope text, expires_at timestamptz)
        LANGUAGE sql SECURITY DEFINER STABLE SET search_path = ''
        AS $$ SELECT t.id, t.owner_id, t.role, t.display_name, t.scope, t.expires_at FROM catch.api_tokens t WHERE t.token_hash = token_hash_in LIMIT 1 $$""")
    op.execute("REVOKE ALL ON FUNCTION catch_private.resolve_api_token(text) FROM PUBLIC, anon, authenticated")
    op.execute("GRANT EXECUTE ON FUNCTION catch_private.resolve_api_token(text) TO catch_api")
    for t in TABLES:
        _owned(t)
    op.execute(f"""CREATE TABLE catch.deleted_accounts (
        user_id VARCHAR NOT NULL,
        deleted_at {TS} NOT NULL,
        PRIMARY KEY (user_id)
    )""")
    op.execute(f"""CREATE TABLE catch.account_restrictions (
        id SERIAL NOT NULL,
        user_id VARCHAR NOT NULL,
        scope VARCHAR NOT NULL,
        reason_code VARCHAR NOT NULL,
        reason_text VARCHAR NOT NULL,
        set_by VARCHAR NOT NULL,
        created_at {TS} NOT NULL,
        expires_at {TS},
        lifted_at {TS},
        lifted_by VARCHAR,
        appeal_text VARCHAR,
        appeal_status VARCHAR,
        appeal_resolution VARCHAR,
        appealed_at {TS},
        PRIMARY KEY (id),
        CONSTRAINT ck_account_restrictions_scope CHECK (scope IN ('publish','clubs','posting')),
        CONSTRAINT ck_account_restrictions_appeal CHECK (appeal_status IS NULL OR appeal_status IN ('open','upheld','overturned'))
    )""")
    op.execute("CREATE INDEX ix_account_restrictions_user_id ON catch.account_restrictions (user_id)")
    op.execute(f"""CREATE TABLE catch.moderation_actions (
        id SERIAL NOT NULL,
        actor_id VARCHAR NOT NULL,
        action VARCHAR NOT NULL,
        subject_user_id VARCHAR NOT NULL,
        restriction_id INTEGER,
        reason_text VARCHAR NOT NULL,
        created_at {TS} NOT NULL,
        PRIMARY KEY (id)
    )""")
    op.execute("CREATE INDEX ix_moderation_actions_actor_id ON catch.moderation_actions (actor_id)")
    op.execute("CREATE INDEX ix_moderation_actions_subject_user_id ON catch.moderation_actions (subject_user_id)")
    op.execute(f"""CREATE TABLE catch.moderator_access_log (
        id SERIAL NOT NULL,
        moderator_id VARCHAR NOT NULL,
        kind VARCHAR NOT NULL,
        target_id VARCHAR,
        created_at {TS} NOT NULL,
        PRIMARY KEY (id)
    )""")
    op.execute("CREATE INDEX ix_moderator_access_log_moderator_id ON catch.moderator_access_log (moderator_id)")
    for t in GLOBAL:
        _global_grants(t)
    for seq in ("account_restrictions_id_seq", "moderation_actions_id_seq", "moderator_access_log_id_seq"):
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE catch.{seq} TO catch_api")
    # How old an account is, for the report-brigading rule. user_profiles has no grant for catch_api, so this is a narrow definer function.
    op.execute("""CREATE OR REPLACE FUNCTION catch_private.account_age_days(uid text) RETURNS integer
        LANGUAGE sql SECURITY DEFINER STABLE SET search_path = ''
        AS $$ SELECT (extract(epoch FROM (now() - p.created_at)) / 86400)::integer FROM catch.user_profiles p WHERE p.id = uid $$""")
    op.execute("REVOKE ALL ON FUNCTION catch_private.account_age_days(text) FROM PUBLIC, anon, authenticated")
    op.execute("GRANT EXECUTE ON FUNCTION catch_private.account_age_days(text) TO catch_api")
    # Retention for the club audit trail. The table stays append-only for anything recent: the one DELETE policy is limited by the
    # database itself to rows older than the retention period, so even a bug in the pruning job cannot remove a recent entry.
    op.execute("GRANT DELETE ON catch.club_audit TO catch_api")
    op.execute(f"CREATE POLICY club_audit_expire ON catch.club_audit FOR DELETE TO catch_api USING (created_at < now() - interval '{AUDIT_RETENTION}')")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS catch_private.account_age_days(text)")
    op.execute("DROP FUNCTION IF EXISTS catch_private.resolve_api_token(text)")
    op.execute("""CREATE FUNCTION catch_private.resolve_api_token(token_hash_in text)
        RETURNS TABLE (token_id integer, owner_id text, role text, display_name text)
        LANGUAGE sql SECURITY DEFINER STABLE SET search_path = ''
        AS $$ SELECT t.id, t.owner_id, t.role, t.display_name FROM catch.api_tokens t WHERE t.token_hash = token_hash_in LIMIT 1 $$""")
    op.execute("REVOKE ALL ON FUNCTION catch_private.resolve_api_token(text) FROM PUBLIC, anon, authenticated")
    op.execute("GRANT EXECUTE ON FUNCTION catch_private.resolve_api_token(text) TO catch_api")
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS catch.{t}")
    op.execute("ALTER TABLE catch.api_tokens DROP COLUMN IF EXISTS expires_at")
    op.execute("ALTER TABLE catch.api_tokens DROP COLUMN IF EXISTS scope")
    op.execute("DROP POLICY IF EXISTS club_audit_expire ON catch.club_audit")
    op.execute("REVOKE DELETE ON catch.club_audit FROM catch_api")
    for t in reversed(GLOBAL):
        op.execute(f"DROP TABLE IF EXISTS catch.{t}")
