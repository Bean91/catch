"""The club audit trail stays append-only for anything recent: the one DELETE policy catch_api has is limited by the database to rows
older than the retention period, so a bug in the pruning job can't remove a recent entry (session 28, migration 0008)."""

from sqlalchemy import text

from catch.sync import account_store


def test_only_expired_audit_rows_can_be_deleted_by_the_runtime_role(runtime, admin, clean):
    with admin.begin() as conn:
        conn.exec_driver_sql("SET LOCAL session_replication_role = replica")  # placeholder club ids, as the other generated rows
        for age, name in (("1 day", "recent"), ("23 months", "inside"), ("25 months", "expired")):
            conn.execute(
                text("INSERT INTO catch.club_audit (club_id, actor_kind, action, reason_text, created_at) VALUES ('c1', 'system', :a, 'x', now() - CAST(:age AS interval))"),
                {"a": name, "age": age},
            )
    with runtime.begin() as conn:  # catch_api itself: no SET ROLE, no tenant
        assert conn.execute(text("DELETE FROM catch.club_audit")).rowcount == 1  # the database lets exactly the expired one go
    with admin.connect() as conn:
        left = sorted(r[0] for r in conn.execute(text("SELECT action FROM catch.club_audit")))
    assert left == ["inside", "recent"]


def test_authenticated_users_can_never_delete_audit_rows(runtime, admin, clean):
    with admin.connect() as conn:
        assert conn.execute(text("SELECT has_table_privilege('authenticated', 'catch.club_audit', 'DELETE')")).scalar() is False
        assert conn.execute(text("SELECT has_table_privilege('authenticated', 'catch.club_audit', 'UPDATE')")).scalar() is False


def test_the_pruning_helper_runs_against_the_real_policies(runtime, admin, clean, monkeypatch):
    from catch.core import db as db_module
    from catch.core import tenant

    monkeypatch.setattr(db_module, "engine", runtime)
    monkeypatch.setattr(tenant, "is_public", lambda: True)  # as in production: no default owner, so the store stays as catch_api
    with admin.begin() as conn:
        conn.exec_driver_sql("SET LOCAL session_replication_role = replica")
        conn.execute(text("INSERT INTO catch.club_audit (club_id, actor_kind, action, reason_text, created_at) VALUES ('c1', 'system', 'old', 'x', now() - interval '800 days')"))
    assert account_store.prune_global()["club_audit"] == 1
