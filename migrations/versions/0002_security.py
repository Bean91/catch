"""Roles, row level security, tenant foreign keys, auth-sync triggers and the SECURITY DEFINER lookups.

Needs a Supabase database (the `auth` schema and the `authenticated` role must exist). The table lists below are
FROZEN copies: tests/test_pg_migrations.py fails if a model gains a table that isn't covered here, so a new owned
table can never ship without RLS — add a new revision for it.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

OWNED = (
    "activities", "activity_samples", "activity_tracks", "activity_weather", "ai_credentials", "ai_usage_events",
    "api_tokens", "athlete_facts", "body_comp", "canonical_activities", "checkins", "coach_conversations",
    "coach_credentials", "coach_feedback", "coach_feedback_revisions", "coach_messages", "coach_settings",
    "daily_scores", "daily_wellness", "events", "food_logs", "goals", "gym_stations", "gyms", "illness_acks",
    "match_decisions", "merge_log", "my_foods", "notes", "notification_log", "nutrition_targets", "oauth_tokens",
    "piece_intervals", "piece_photos", "pieces", "planned_workouts", "push_subscriptions", "recommendations",
    "routes", "saved_meals", "settings", "strength_sets", "strength_templates", "strokes", "sync_state",
    "technique_notes", "training_phases", "wellness_readings",
)
SHARED = ("exercises", "foods", "workout_templates")  # owner_id IS NULL = global read-only reference rows
PROFILES = "user_profiles"
GLOBAL_CACHE = "weather_cells"  # public weather keyed by cell + day; carries no user id

# (child, column, parent, on delete) — every cross-row reference whose model declares a ForeignKey and whose
# parent is strictly owned. The composite key (owner_id, id) makes the foreign-key check itself refuse a parent
# owned by someone else (a plain FK check reads the parent as the table owner, so RLS can't stop that).
TENANT_FKS = (
    ("activities", "canonical_id", "canonical_activities", None),
    ("activities", "linked_activity_id", "activities", None),
    ("activity_samples", "activity_id", "activities", None),
    ("activity_tracks", "activity_id", "activities", None),
    ("activity_tracks", "route_id", "routes", None),
    ("activity_weather", "activity_id", "activities", None),
    ("canonical_activities", "absorbed_into_piece_id", "pieces", None),
    ("coach_messages", "conversation_id", "coach_conversations", None),
    ("gym_stations", "gym_id", "gyms", None),
    ("piece_intervals", "piece_id", "pieces", None),
    ("piece_photos", "piece_id", "pieces", None),
    ("pieces", "canonical_id", "canonical_activities", None),
    ("pieces", "concept2_activity_id", "activities", None),
    ("pieces", "window_activity_id", "activities", None),
    ("planned_workouts", "event_id", "events", "SET NULL"),
    ("planned_workouts", "linked_canonical_id", "canonical_activities", "SET NULL"),
    ("strength_sets", "activity_id", "activities", None),
    ("strength_sets", "gym_station_id", "gym_stations", None),
    ("strokes", "activity_id", "activities", None),
    ("training_phases", "event_id", "events", "SET NULL"),
)

UID = "(SELECT auth.uid())::text"


def _x(sql: str) -> None:
    op.execute(sql)


def upgrade() -> None:
    _x("""DO $$ BEGIN
        IF to_regnamespace('auth') IS NULL OR NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
            RAISE EXCEPTION 'Catch public migrations need a Supabase database (auth schema + authenticated role)';
        END IF;
    END $$""")

    # --- the runtime role: can log in, can do nothing until a request SETs ROLE authenticated -------------------------
    _x("""DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'catch_api') THEN
            CREATE ROLE catch_api LOGIN NOINHERIT NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
        END IF;
    END $$""")
    _x("ALTER ROLE catch_api SET statement_timeout = '30s'")
    _x("ALTER ROLE catch_api SET search_path = catch, public")
    _x("GRANT authenticated TO catch_api")

    _x("REVOKE ALL ON SCHEMA catch FROM PUBLIC")
    _x("REVOKE ALL ON SCHEMA catch FROM anon")
    _x("GRANT USAGE ON SCHEMA catch TO authenticated")
    _x("REVOKE ALL ON ALL TABLES IN SCHEMA catch FROM PUBLIC, anon, authenticated, service_role")
    for t in OWNED + SHARED + (PROFILES,):
        _x(f"GRANT SELECT, INSERT, UPDATE, DELETE ON catch.{t} TO authenticated")
    _x(f"GRANT SELECT, INSERT ON catch.{GLOBAL_CACHE} TO authenticated")
    _x("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA catch TO authenticated")

    # --- row level security --------------------------------------------------------------------------------------
    for t in OWNED:
        _x(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
        _x(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
        _x(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO authenticated USING (owner_id = {UID})")
        _x(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO authenticated WITH CHECK (owner_id = {UID})")
        _x(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO authenticated USING (owner_id = {UID}) WITH CHECK (owner_id = {UID})")
        _x(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO authenticated USING (owner_id = {UID})")
    for t in SHARED:
        _x(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
        _x(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
        _x(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO authenticated USING (owner_id IS NULL OR owner_id = {UID})")
        _x(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO authenticated WITH CHECK (owner_id = {UID})")
        _x(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO authenticated USING (owner_id = {UID}) WITH CHECK (owner_id = {UID})")
        _x(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO authenticated USING (owner_id = {UID})")
    t = PROFILES
    _x(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
    _x(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
    _x(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO authenticated USING (id = {UID})")
    _x(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO authenticated WITH CHECK (id = {UID})")
    _x(f"CREATE POLICY {t}_update ON catch.{t} FOR UPDATE TO authenticated USING (id = {UID}) WITH CHECK (id = {UID})")
    _x(f"CREATE POLICY {t}_delete ON catch.{t} FOR DELETE TO authenticated USING (id = {UID})")
    t = GLOBAL_CACHE
    _x(f"ALTER TABLE catch.{t} ENABLE ROW LEVEL SECURITY")
    _x(f"ALTER TABLE catch.{t} FORCE ROW LEVEL SECURITY")
    _x(f"CREATE POLICY {t}_select ON catch.{t} FOR SELECT TO authenticated USING (true)")
    _x(f"CREATE POLICY {t}_insert ON catch.{t} FOR INSERT TO authenticated WITH CHECK (true)")

    # --- composite tenant foreign keys ---------------------------------------------------------------------------
    for parent in sorted({p for _, _, p, _ in TENANT_FKS}):
        _x(f"ALTER TABLE catch.{parent} ADD CONSTRAINT uq_owner_id_{parent} UNIQUE (owner_id, id)")
    for child, col, parent, ondelete in TENANT_FKS:
        action = f" ON DELETE SET NULL ({col})" if ondelete == "SET NULL" else ""
        _x(
            f"ALTER TABLE catch.{child} ADD CONSTRAINT fk_tenant_{child}_{col} "
            f"FOREIGN KEY (owner_id, {col}) REFERENCES catch.{parent} (owner_id, id){action}"
        )

    # --- non-exposed schema for the few things the runtime role may EXECUTE ---------------------------------------
    _x("CREATE SCHEMA IF NOT EXISTS catch_private")
    _x("REVOKE ALL ON SCHEMA catch_private FROM PUBLIC, anon, authenticated")
    _x("GRANT USAGE ON SCHEMA catch_private TO catch_api")

    # Access tokens can't be revoked before `exp`; the documented check is that the session still exists.
    _x("""CREATE OR REPLACE FUNCTION catch_private.session_is_live(sid uuid) RETURNS boolean
        LANGUAGE sql SECURITY DEFINER STABLE SET search_path = ''
        AS $$ SELECT EXISTS (SELECT 1 FROM auth.sessions s WHERE s.id = sid AND (s.not_after IS NULL OR s.not_after > now())) $$""")
    # A device token (MCP/coach) is resolved before any owner is known.
    _x("""CREATE OR REPLACE FUNCTION catch_private.resolve_api_token(token_hash_in text)
        RETURNS TABLE (token_id integer, owner_id text, role text, display_name text)
        LANGUAGE sql SECURITY DEFINER STABLE SET search_path = ''
        AS $$ SELECT t.id, t.owner_id, t.role, t.display_name FROM catch.api_tokens t WHERE t.token_hash = token_hash_in LIMIT 1 $$""")
    # The scheduled tick iterates users; each is then handled under that user's own context.
    _x("""CREATE OR REPLACE FUNCTION catch_private.list_user_ids() RETURNS SETOF text
        LANGUAGE sql SECURITY DEFINER STABLE SET search_path = ''
        AS $$ SELECT p.id FROM catch.user_profiles p ORDER BY p.created_at $$""")
    for fn in ("session_is_live(uuid)", "resolve_api_token(text)", "list_user_ids()"):
        _x(f"REVOKE ALL ON FUNCTION catch_private.{fn} FROM PUBLIC, anon, authenticated")
        _x(f"GRANT EXECUTE ON FUNCTION catch_private.{fn} TO catch_api")

    # --- keep user_profiles in step with auth.users --------------------------------------------------------------
    _x("""CREATE OR REPLACE FUNCTION catch_private.handle_new_user() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
        AS $$ BEGIN
            INSERT INTO catch.user_profiles (id, email, display_name, created_at)
            VALUES (NEW.id::text, NEW.email, NEW.raw_user_meta_data ->> 'display_name', now())
            ON CONFLICT (id) DO NOTHING;
            RETURN NEW;
        EXCEPTION WHEN OTHERS THEN
            -- never block a sign-up: the first authenticated request creates the profile instead
            RAISE WARNING 'catch: profile creation failed for %: %', NEW.id, SQLERRM;
            RETURN NEW;
        END $$""")
    _x("""CREATE OR REPLACE FUNCTION catch_private.handle_deleted_user() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
        AS $$ BEGIN
            DELETE FROM catch.user_profiles WHERE id = OLD.id::text;  -- ON DELETE CASCADE removes every owned row
            RETURN OLD;
        END $$""")
    _x("REVOKE ALL ON FUNCTION catch_private.handle_new_user() FROM PUBLIC, anon, authenticated")
    _x("REVOKE ALL ON FUNCTION catch_private.handle_deleted_user() FROM PUBLIC, anon, authenticated")
    _x("DROP TRIGGER IF EXISTS catch_on_auth_user_created ON auth.users")
    _x("CREATE TRIGGER catch_on_auth_user_created AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION catch_private.handle_new_user()")
    _x("DROP TRIGGER IF EXISTS catch_on_auth_user_deleted ON auth.users")
    _x("CREATE TRIGGER catch_on_auth_user_deleted AFTER DELETE ON auth.users FOR EACH ROW EXECUTE FUNCTION catch_private.handle_deleted_user()")


def downgrade() -> None:
    _x("DROP TRIGGER IF EXISTS catch_on_auth_user_deleted ON auth.users")
    _x("DROP TRIGGER IF EXISTS catch_on_auth_user_created ON auth.users")
    _x("DROP SCHEMA IF EXISTS catch_private CASCADE")
    for child, col, _, _ in TENANT_FKS:
        _x(f"ALTER TABLE catch.{child} DROP CONSTRAINT IF EXISTS fk_tenant_{child}_{col}")
    for parent in sorted({p for _, _, p, _ in TENANT_FKS}):
        _x(f"ALTER TABLE catch.{parent} DROP CONSTRAINT IF EXISTS uq_owner_id_{parent}")
    for t in OWNED + SHARED + (PROFILES, GLOBAL_CACHE):
        for cmd in ("select", "insert", "update", "delete"):
            _x(f"DROP POLICY IF EXISTS {t}_{cmd} ON catch.{t}")
        _x(f"ALTER TABLE catch.{t} NO FORCE ROW LEVEL SECURITY")
        _x(f"ALTER TABLE catch.{t} DISABLE ROW LEVEL SECURITY")
    _x("REVOKE ALL ON ALL TABLES IN SCHEMA catch FROM authenticated")
    _x("REVOKE ALL ON ALL SEQUENCES IN SCHEMA catch FROM authenticated")
    _x("REVOKE USAGE ON SCHEMA catch FROM authenticated")
    _x("REVOKE authenticated FROM catch_api")
    _x("DROP ROLE IF EXISTS catch_api")
