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

TABLES: tuple = ()  # owned (owner_id + forced RLS)
GLOBAL = ("deleted_accounts",)  # catch_api only
TS = "TIMESTAMP WITH TIME ZONE"
POLICY_COUNT_DELTAS = {"club_audit": 1}  # tests/pg/test_migrations.py adds these to the counts it derives from earlier revisions
AUDIT_RETENTION = "24 months"


def _global_grants(t: str) -> None:
    op.execute(f"REVOKE ALL ON catch.{t} FROM PUBLIC, anon, authenticated, service_role")
    op.execute(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO catch_api")
    op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO catch_api USING (true)")
    op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO catch_api WITH CHECK (true)")
    op.execute(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO catch_api USING (true) WITH CHECK (true)")
    op.execute(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO catch_api USING (true)")


def upgrade() -> None:
    op.execute(f"""CREATE TABLE catch.deleted_accounts (
        user_id VARCHAR NOT NULL,
        deleted_at {TS} NOT NULL,
        PRIMARY KEY (user_id)
    )""")
    for t in GLOBAL:
        _global_grants(t)
    # Retention for the club audit trail. The table stays append-only for anything recent: the one DELETE policy is limited by the
    # database itself to rows older than the retention period, so even a bug in the pruning job cannot remove a recent entry.
    op.execute("GRANT DELETE ON catch.club_audit TO catch_api")
    op.execute(f"CREATE POLICY club_audit_expire ON catch.club_audit FOR DELETE TO catch_api USING (created_at < now() - interval '{AUDIT_RETENTION}')")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS club_audit_expire ON catch.club_audit")
    op.execute("REVOKE DELETE ON catch.club_audit FROM catch_api")
    for t in reversed(GLOBAL):
        op.execute(f"DROP TABLE IF EXISTS catch.{t}")
