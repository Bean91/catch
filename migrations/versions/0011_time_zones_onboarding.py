"""Session 32 (docs/time.md, docs/performance.md): per-user time zones, onboarding progress, and the indexes the hot reads need.

* `user_profiles` gains the home zone, the follow-my-device switch and onboarding progress. Every account that exists when this runs
  is marked onboarding-complete, so nobody who already uses Catch is sent through setup again (new rows start NULL = not done).
  0002 already lets a person update their own profile row (policy `id = auth.uid()`), which covers the new columns.
* `user_zone_periods` (owned, forced RLS): where the athlete was, from when — written by the app from a phone/browser report or a
  watch-recorded offset.
* `local_date`/`local_tz` on activities, canonical_activities, food_logs and body_comp: the day a record happened on, in the zone it
  happened in. Filled for existing rows by the app itself (catch.core.localtime's backfill, run once per user by the sync tick).
* Indexes: `activities(canonical_id)` and `strokes(activity_id)` existed only on the Pi's SQLite file; Postgres scanned without them.

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

TABLES = ("user_zone_periods",)  # owned (owner_id + forced RLS)
GLOBAL: tuple[str, ...] = ()
POLICY_COUNT_ABSOLUTE = {"user_zone_periods": 4}
UID = "(SELECT auth.uid())::text"
TS = "TIMESTAMP WITH TIME ZONE"

STAMPED = ("activities", "canonical_activities", "food_logs", "body_comp")
INDEXES = (
    ("ix_activities_canonical_id", "activities", "canonical_id"),
    ("ix_activities_owner_start", "activities", "owner_id, start"),
    ("ix_strokes_activity_id", "strokes", "activity_id"),
    ("ix_canonical_activities_owner_local_date", "canonical_activities", "owner_id, local_date"),
    ("ix_canonical_activities_owner_start", "canonical_activities", "owner_id, start"),
    ("ix_body_comp_owner_ts", "body_comp", "owner_id, ts"),
    ("ix_food_logs_owner_local_date", "food_logs", "owner_id, local_date"),
    ("ix_user_zone_periods_owner_start", "user_zone_periods", "owner_id, start_utc"),
)


def _owned(t: str) -> None:
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO authenticated")
    op.execute(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO authenticated USING (owner_id = {UID})")
    op.execute(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO authenticated WITH CHECK (owner_id = {UID})")
    op.execute(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO authenticated USING (owner_id = {UID}) WITH CHECK (owner_id = {UID})")
    op.execute(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO authenticated USING (owner_id = {UID})")


def upgrade() -> None:
    op.execute("ALTER TABLE catch.user_profiles ADD COLUMN timezone VARCHAR")
    op.execute("ALTER TABLE catch.user_profiles ADD COLUMN follow_device_zone BOOLEAN")
    op.execute("ALTER TABLE catch.user_profiles ADD COLUMN onboarding_state VARCHAR")
    op.execute("ALTER TABLE catch.user_profiles ADD COLUMN onboarding_step INTEGER")
    op.execute("ALTER TABLE catch.user_profiles ADD COLUMN onboarding_json VARCHAR")
    op.execute(f"ALTER TABLE catch.user_profiles ADD COLUMN onboarding_completed_at {TS}")
    op.execute("UPDATE catch.user_profiles SET onboarding_state = 'completed', onboarding_completed_at = now() WHERE onboarding_state IS NULL")
    for t in STAMPED:
        op.execute(f"ALTER TABLE catch.{t} ADD COLUMN local_date DATE")
        op.execute(f"ALTER TABLE catch.{t} ADD COLUMN local_tz VARCHAR")
    op.execute(f"""CREATE TABLE catch.user_zone_periods (
        owner_id VARCHAR NOT NULL,
        id SERIAL NOT NULL,
        start_utc {TS} NOT NULL,
        tz VARCHAR NOT NULL,
        source VARCHAR NOT NULL,
        created_at {TS} NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(owner_id) REFERENCES catch.user_profiles (id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_user_zone_periods_owner_id ON catch.user_zone_periods (owner_id)")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE catch.user_zone_periods_id_seq TO authenticated")
    for t in TABLES:
        _owned(t)
    for name, table, cols in INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON catch.{table} ({cols})")


def downgrade() -> None:
    for name, _, _ in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS catch.{name}")
    op.execute("DROP TABLE IF EXISTS catch.user_zone_periods")
    for t in STAMPED:
        op.execute(f"ALTER TABLE catch.{t} DROP COLUMN IF EXISTS local_tz")
        op.execute(f"ALTER TABLE catch.{t} DROP COLUMN IF EXISTS local_date")
    for col in ("onboarding_completed_at", "onboarding_json", "onboarding_step", "onboarding_state", "follow_device_zone", "timezone"):
        op.execute(f"ALTER TABLE catch.user_profiles DROP COLUMN IF EXISTS {col}")
