"""Per-user provider connections (session 25): the `provider_connections` table with forced RLS, plus the backoff and
paced-backfill columns on `sync_state`.

A new revision rather than an edit of 0002: that revision's table lists are FROZEN (see its docstring).

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLES = ("provider_connections",)
UID = "(SELECT auth.uid())::text"


def upgrade() -> None:
    op.execute("""CREATE TABLE catch.provider_connections (
        owner_id VARCHAR NOT NULL,
        provider VARCHAR NOT NULL,
        auth_method VARCHAR NOT NULL,
        status VARCHAR NOT NULL,
        status_detail VARCHAR,
        account_id VARCHAR,
        scopes_json VARCHAR,
        access_enc VARCHAR,
        refresh_enc VARCHAR,
        credential_enc VARCHAR,
        key_id VARCHAR,
        last4 VARCHAR NOT NULL,
        expires_at TIMESTAMP WITH TIME ZONE,
        credential_expires_on DATE,
        connected_at TIMESTAMP WITH TIME ZONE NOT NULL,
        last_validated_at TIMESTAMP WITH TIME ZONE,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (owner_id, provider),
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")
    op.execute("ALTER TABLE catch.sync_state ADD COLUMN next_attempt_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE catch.sync_state ADD COLUMN backfill_cursor VARCHAR")
    for t in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO authenticated")
        op.execute(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO authenticated USING (owner_id = {UID})")
        op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO authenticated WITH CHECK (owner_id = {UID})")
        op.execute(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO authenticated USING (owner_id = {UID}) WITH CHECK (owner_id = {UID})")
        op.execute(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO authenticated USING (owner_id = {UID})")


def downgrade() -> None:
    # Connections hold credentials only; the imported data is untouched. Reconnect after re-upgrading.
    op.execute("ALTER TABLE catch.sync_state DROP COLUMN IF EXISTS backfill_cursor")
    op.execute("ALTER TABLE catch.sync_state DROP COLUMN IF EXISTS next_attempt_at")
    op.execute("DROP TABLE IF EXISTS catch.provider_connections")
