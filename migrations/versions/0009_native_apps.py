"""Session 30 (native iOS/Android apps, docs/mobile/): native push tokens and health-import consent.

`native_push_tokens` is GLOBAL (catch_api only, like `deleted_accounts`): a device token must belong to exactly one account at a
time, which a per-owner table cannot enforce. `health_consents` is an ordinary owned table (owner_id + forced RLS).

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

TABLES = ("health_consents",)  # owned (owner_id + forced RLS)
GLOBAL = ("native_push_tokens",)  # catch_api only
POLICY_COUNT_ABSOLUTE = {"health_consents": 4, "native_push_tokens": 4}  # tests/pg/test_migrations.py adds these to the counts it derives from earlier revisions
UID = "(SELECT auth.uid())::text"
TS = "TIMESTAMP WITH TIME ZONE"


def _owned(t: str) -> None:
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO authenticated")
    op.execute(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO authenticated USING (owner_id = {UID})")
    op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO authenticated WITH CHECK (owner_id = {UID})")
    op.execute(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO authenticated USING (owner_id = {UID}) WITH CHECK (owner_id = {UID})")
    op.execute(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO authenticated USING (owner_id = {UID})")


def _global(t: str) -> None:
    op.execute(f"REVOKE ALL ON catch.{t} FROM PUBLIC, anon, authenticated, service_role")
    op.execute(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO catch_api")
    op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO catch_api USING (true)")
    op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO catch_api WITH CHECK (true)")
    op.execute(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO catch_api USING (true) WITH CHECK (true)")
    op.execute(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO catch_api USING (true)")


def upgrade() -> None:
    op.execute(f"""CREATE TABLE catch.native_push_tokens (
        id SERIAL NOT NULL,
        owner_id VARCHAR NOT NULL,
        platform VARCHAR NOT NULL,
        token VARCHAR NOT NULL,
        environment VARCHAR NOT NULL,
        app_id VARCHAR NOT NULL,
        label VARCHAR,
        created_at {TS} NOT NULL,
        last_seen_at {TS} NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_native_push_platform_token UNIQUE (platform, token),
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_native_push_tokens_owner_id ON catch.native_push_tokens (owner_id)")
    op.execute(f"""CREATE TABLE catch.health_consents (
        owner_id VARCHAR NOT NULL,
        id SERIAL NOT NULL,
        platform VARCHAR NOT NULL,
        categories_json VARCHAR NOT NULL,
        granted_at {TS} NOT NULL,
        revoked_at {TS},
        last_import_at {TS},
        notice_version VARCHAR NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_health_consent_owner_platform UNIQUE (owner_id, platform),
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_health_consents_owner_id ON catch.health_consents (owner_id)")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE catch.health_consents_id_seq TO authenticated")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE catch.native_push_tokens_id_seq TO catch_api")
    for t in TABLES:
        _owned(t)
    for t in GLOBAL:
        _global(t)


def downgrade() -> None:
    for t in reversed(TABLES + GLOBAL):
        op.execute(f"DROP TABLE IF EXISTS catch.{t}")
