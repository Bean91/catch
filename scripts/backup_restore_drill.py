"""Backup and restore drill for Catch's Postgres schemas, on a LOCAL throwaway `supabase start` stack only (launch audit §E).

What it proves: a `pg_dump` of Catch's three schemas (`catch`, `catch_private`, `catch_club`) restores with every table, row, forced
RLS flag, policy, function and grant intact, and isolation still holds afterwards. What it found (session 31): the two triggers on
`auth.users` that create and delete a user's profile live on *Supabase's* table, so a schema-scoped dump does not carry them and
`DROP SCHEMA … CASCADE` removes them — a restore must re-create them (docs/operations-runbook.md "Restore"). The drill checks for
that and re-creates them with the exact statements from migration 0002.

Destructive on the target (drops and restores those schemas). Refuses any non-loopback database.

    DRILL_ADMIN_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres \\
    DRILL_SUPABASE_URL=http://127.0.0.1:54321 DRILL_SECRET_KEY=… uv run python scripts/backup_restore_drill.py
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psycopg

SCHEMAS = ("catch", "catch_private", "catch_club")
AUTH_TRIGGERS = (  # migration 0002_security.py, verbatim
    "CREATE TRIGGER catch_on_auth_user_created AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION catch_private.handle_new_user()",
    "CREATE TRIGGER catch_on_auth_user_deleted AFTER DELETE ON auth.users FOR EACH ROW EXECUTE FUNCTION catch_private.handle_deleted_user()",
)
RESULTS: list[tuple[bool, str]] = []


def record(ok: bool, label: str, detail: str = "") -> None:
    RESULTS.append((ok, label))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}{' — ' + detail if detail else ''}")


def snapshot(conn) -> dict:
    tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'catch' ORDER BY 1").fetchall()]
    counts = {t: conn.execute(f'SELECT count(*) FROM catch."{t}"').fetchone()[0] for t in tables}  # noqa: S608 — names from pg_tables
    rls = conn.execute("SELECT count(*) FILTER (WHERE relrowsecurity AND relforcerowsecurity), count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                       "WHERE n.nspname = 'catch' AND c.relkind = 'r' AND c.relname <> 'alembic_version'").fetchone()
    return {
        "counts": counts,
        "rls_forced": rls[0], "tables": rls[1],
        "policies": conn.execute("SELECT count(*) FROM pg_policies WHERE schemaname = ANY(%s)", (list(SCHEMAS),)).fetchone()[0],
        "functions": conn.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = ANY(%s)", (list(SCHEMAS),)).fetchone()[0],
        "grants": conn.execute("SELECT count(*) FROM information_schema.role_table_grants WHERE table_schema = ANY(%s)", (list(SCHEMAS),)).fetchone()[0],
        "auth_triggers": sorted(r[0] for r in conn.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = 'auth.users'::regclass AND tgname LIKE 'catch_%'").fetchall()),
        "revision": conn.execute("SELECT version_num FROM catch.alembic_version").fetchone()[0],
    }


def main() -> int:
    admin_url, sb, sec = os.environ["DRILL_ADMIN_DB_URL"], os.environ["DRILL_SUPABASE_URL"].rstrip("/"), os.environ["DRILL_SECRET_KEY"]
    if urlsplit(admin_url).hostname not in ("127.0.0.1", "localhost") or urlsplit(sb).hostname not in ("127.0.0.1", "localhost"):
        raise SystemExit("Refusing: the drill drops and restores schemas, local stack only")
    adm = {"apikey": sec, "authorization": f"Bearer {sec}"}
    uids = []
    for label in ("a", "b"):
        r = httpx.post(f"{sb}/auth/v1/admin/users", headers=adm, json={"email": f"drill-{label}-{secrets.token_hex(3)}@example.com", "password": secrets.token_urlsafe(16) + "aA1!", "email_confirm": True}, timeout=20)
        r.raise_for_status()
        uids.append(r.json()["id"])
    try:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            for uid in uids:
                conn.execute("INSERT INTO catch.notes (owner_id, date, text, created_at) VALUES (%s, current_date, %s, now())", (uid, f"drill note {uid}"))
                conn.execute("INSERT INTO catch.daily_wellness (owner_id, date, source, resting_hr, updated_at) SELECT %s, d::date, 'garmin', 50, now() FROM generate_series(current_date - 99, current_date, '1 day') d", (uid,))
            before = snapshot(conn)
        record(before["rls_forced"] == before["tables"] and len(before["auth_triggers"]) == 2, "baseline: every catch table has forced RLS, both auth.users triggers present",
               f"{before['tables']} tables, {before['policies']} policies, {before['functions']} functions, revision {before['revision']}")

        with tempfile.TemporaryDirectory(prefix="catch-drill-") as d:
            dump = Path(d) / "catch.dump"
            subprocess.run(["pg_dump", "--format=custom", *[f"--schema={s}" for s in SCHEMAS], f"--file={dump}", admin_url], check=True)
            record(dump.stat().st_size > 0, "pg_dump of catch, catch_private, catch_club", f"{dump.stat().st_size / 1024:.0f} KiB")
            with psycopg.connect(admin_url, autocommit=True) as conn:
                conn.execute("DROP SCHEMA catch, catch_private, catch_club CASCADE")
                gone = conn.execute("SELECT count(*) FROM pg_namespace WHERE nspname = ANY(%s)", (list(SCHEMAS),)).fetchone()[0]
            record(gone == 0, "schemas dropped (simulated loss)")
            restored = subprocess.run(["pg_restore", "--exit-on-error", f"--dbname={admin_url}", str(dump)], capture_output=True, text=True)
            record(restored.returncode == 0, "pg_restore completed", restored.stderr.strip()[:200])

        with psycopg.connect(admin_url, autocommit=True) as conn:
            after = snapshot(conn)
            record(after["counts"] == before["counts"], "every table's row count is identical", f"{sum(after['counts'].values())} rows")
            for key in ("rls_forced", "tables", "policies", "functions", "grants", "revision"):
                record(after[key] == before[key], f"{key} restored", f"{before[key]} -> {after[key]}")
            if after["auth_triggers"] != before["auth_triggers"]:
                print(f"[NOTE] a schema-level restore drops the auth.users triggers {sorted(set(before['auth_triggers']) - set(after['auth_triggers']))} (expected; runbook step re-creates them)")
                for stmt in AUTH_TRIGGERS:
                    conn.execute(stmt.replace("CREATE TRIGGER", "CREATE OR REPLACE TRIGGER"))
                record(len(snapshot(conn)["auth_triggers"]) == 2, "auth.users triggers re-created (runbook step)")
            else:
                record(True, "auth.users triggers survive a schema-level restore")

        # Isolation after restore, over the runtime role's own path (SET LOCAL ROLE authenticated + the user's claims).
        with psycopg.connect(admin_url) as conn:
            for me, other in ((uids[0], uids[1]), (uids[1], uids[0])):
                conn.execute("SET LOCAL ROLE authenticated")
                conn.execute("SELECT set_config('request.jwt.claims', %s, true), set_config('request.jwt.claim.sub', %s, true)", (json.dumps({"sub": me, "role": "authenticated"}), me))
                seen = [r[0] for r in conn.execute("SELECT owner_id FROM catch.notes").fetchall()]
                conn.rollback()
                record(seen == [me], "after restore a user still sees only their own rows", f"{len(seen)} visible")
    finally:
        for uid in uids:
            httpx.request("DELETE", f"{sb}/auth/v1/admin/users/{uid}", headers=adm, json={"should_soft_delete": False}, timeout=20)
        with psycopg.connect(admin_url, autocommit=True) as conn:
            left = conn.execute("SELECT count(*) FROM catch.user_profiles WHERE id = ANY(%s)", (uids,)).fetchone()[0]
        record(left == 0, "the deletion trigger still cascades after the drill", f"{left} profiles left")
    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
