from __future__ import annotations

from catch.core import tenant
import argparse
import secrets

from catch.core.config import settings
from catch.core.db import get_session, init_db
from catch.sync.scheduler import FIT_DIR, SOURCES, run_sync
from catch.sync import state


def cmd_sync(args: argparse.Namespace) -> None:
    init_db()
    result = run_sync(args.source, days=args.days)
    if "error" in result:
        raise SystemExit(f"{args.source} sync failed: {result['error']}")
    print(f"{args.source}: {result}")


def cmd_backfill(args: argparse.Namespace) -> None:
    init_db()
    days = args.days or settings.backfill_days
    with get_session() as session:
        from catch.sync import connections

        for source in SOURCES:
            if source == "whoop" and not connections.is_connected(session, "whoop"):
                print("whoop: not connected, skipped")
                continue
            state.record_attempt(session, source)
            try:
                if source == "garmin":
                    from catch.sync.garmin_client import GarminClient

                    totals = GarminClient(session).backfill(days, FIT_DIR)
                    print(f"garmin backfill ({days}d): {totals}")
                elif source == "withings":
                    from catch.sync.withings_client import sync as withings_sync

                    n = withings_sync(session, days=days)
                    print(f"withings backfill ({days}d): {n} body_comp rows")
                elif source == "whoop":
                    from catch.sync.whoop_client import sync as whoop_sync

                    print(f"whoop backfill ({days}d): {whoop_sync(session, days=days)} records")
                else:
                    from catch.sync.concept2_client import sync as concept2_sync

                    result = concept2_sync(session, days=days)
                    print(f"concept2 backfill ({days}d): {result}")
                state.record_success(session, source)
            except Exception as exc:
                state.record_error(session, source, str(exc))
                print(f"{source} backfill failed: {exc}")
        from catch.sync.scoring import recompute_scores

        n = recompute_scores(session)
        print(f"recomputed {n} daily_scores rows")


def cmd_whoop_check(args: argparse.Namespace) -> None:
    """The manual Whoop connection test: one request per scope, counts only (no tokens, names or
    e-mail addresses are printed)."""
    init_db()
    from catch.sync import whoop_client

    if not whoop_client.configured():
        raise SystemExit("WHOOP_CLIENT_ID / WHOOP_CLIENT_SECRET / WHOOP_REDIRECT_URI aren't set (names only — see .env.example).")
    with get_session() as session:
        try:
            report = whoop_client.check(session)
        except whoop_client.WhoopError as exc:
            raise SystemExit(f"whoop check failed: {exc}")
    for key, value in report.items():
        print(f"{key}: {value}")


def cmd_backfill_gps(args: argparse.Namespace) -> None:
    """Parses GPS tracks out of every FIT file already on disk (the sync loop only reaches the
    sync window), then groups rowing tracks into routes; --weather also fetches weather."""
    init_db()
    with get_session() as session:
        from catch.sync.tracks import backfill_tracks

        print(f"tracks: {backfill_tracks(session, force=args.force)}")
        from catch.sync.routes import assign_all_routes

        print(f"routes: {assign_all_routes(session)}")
        if args.weather:
            import time

            from catch.sync.weather import enrich_pending, pending_count
            from catch.sync.weather_client import minute_budget_exhausted

            total = {"processed": 0, "ok": 0}
            waits = 0
            while True:
                result = enrich_pending(session, limit=20)
                if result.get("disabled"):
                    print("weather: disabled in settings (on_water.weather_enabled)")
                    break
                total["processed"] += result["processed"]
                total["ok"] += result["ok"]
                if result["processed"] > 0:
                    continue
                left = pending_count(session)
                if left and result.get("stopped") == "provider_unavailable" and minute_budget_exhausted() and waits < 10:
                    waits += 1
                    print(f"weather: per-minute request limit reached, waiting 60 s ({left} left)")
                    time.sleep(61)
                    continue
                note = f" — {left} still pending (provider unreachable or budget spent; run again later)" if left else ""
                print(f"weather: {total}{note}")
                break


def cmd_token_create(args: argparse.Namespace) -> None:
    from catch.api.deps import hash_token
    from catch.core.models import ApiToken

    init_db()
    raw_token = secrets.token_urlsafe(32)
    with get_session() as session:
        session.add(
            ApiToken(
                name=args.name, token_hash=hash_token(raw_token),
                role=None if args.role == "athlete" else args.role, display_name=(args.display_name or "").strip() or None,
            )
        )
        session.commit()
    # Shown exactly once — only the hash is ever stored (CLAUDE.md: never print secrets to
    # logs, but this is the one deliberate exception, same as an argon2 password hash
    # generated at setup time: there is no other way to hand the raw value to the user).
    kind = "coach token" if args.role == "coach" else "Device token"
    print(f"{kind} for '{args.name}' (save this now, it will not be shown again):\n{raw_token}")


def cmd_token_list(args: argparse.Namespace) -> None:
    from catch.core.models import ApiToken
    from sqlmodel import select

    init_db()
    with get_session() as session:
        rows = session.exec(select(ApiToken)).all()
    if not rows:
        print("No device tokens.")
        return
    for row in rows:
        print(f"{row.id}\t{row.name}\t{row.role or 'athlete'}\tcreated {row.created_at}\tlast used {row.last_used_at or 'never'}")


def cmd_db_upgrade(args: argparse.Namespace) -> None:
    import os
    import subprocess
    import sys

    if not os.environ.get("DATABASE_ADMIN_URL"):
        raise SystemExit("Set DATABASE_ADMIN_URL (an admin/migration role — never the runtime catch_api role).")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", args.revision], check=True)


def cmd_db_check(args: argparse.Namespace) -> None:
    from catch.core import db_pg
    from catch.core.db import engine

    if not settings.is_public:
        raise SystemExit("db check is for CATCH_DEPLOYMENT=public.")
    report = {**db_pg.role_report(engine), **db_pg.rls_probe(engine), "pool_mode": settings.db_pool_mode}
    for key, value in report.items():
        print(f"{key}: {value}")
    if report["superuser"] or report["bypass_rls"] or not report["sees_nothing_as_stranger"] or not report["cannot_write_for_another_user"]:
        raise SystemExit("FAILED: this connection would not be protected by row level security")
    print("ok")


def cmd_db_current(args: argparse.Namespace) -> None:
    """Applied vs expected migration revision, read with the admin URL (the runtime role cannot read the version table). Run it
    after `db upgrade` and before `fastapi deploy`: code newer than the database otherwise shows up only as runtime errors."""
    import os

    from catch.core import db_pg

    if not os.environ.get("DATABASE_ADMIN_URL"):
        raise SystemExit("Set DATABASE_ADMIN_URL.")
    engine = db_pg.build_pg_engine(os.environ["DATABASE_ADMIN_URL"], rls=False)
    try:
        applied = db_pg.applied_revision(engine)
    finally:
        engine.dispose()
    print(f"applied: {applied}\nexpected by this code: {db_pg.EXPECTED_SCHEMA_REVISION}")
    if applied != db_pg.EXPECTED_SCHEMA_REVISION:
        raise SystemExit("MISMATCH: run `catch db upgrade` before deploying this build" if applied else "no migration applied")
    print("ok")


def cmd_db_seed(args: argparse.Namespace) -> None:
    """Global reference rows (the exercise library, example templates) for a public database — run with the
    admin URL, since the runtime role can't write rows with no owner."""
    import os

    from catch.core import db as db_module

    if not os.environ.get("DATABASE_ADMIN_URL"):
        raise SystemExit("Set DATABASE_ADMIN_URL.")
    from catch.core.db_pg import build_pg_engine

    import dataclasses

    from sqlalchemy import event

    from catch.core import config

    # Global rows are owner-less; in the default personal mode they would be stamped with the Pi's owner and
    # refused by the foreign key. The module-level engine was built for SQLite before this runs, so only the mode flips.
    config.settings = dataclasses.replace(config.settings, deployment="public")
    engine = build_pg_engine(os.environ["DATABASE_ADMIN_URL"], rls=False)

    # The tables live in the non-exposed `catch` schema; the admin login's default search_path is `public`. A
    # connect-time listener rather than the `options` startup parameter, which Supavisor rejects.
    @event.listens_for(engine, "connect")
    def _search_path(dbapi_conn, _record) -> None:
        dbapi_conn.autocommit = True
        dbapi_conn.execute("SET search_path TO catch, public")
        dbapi_conn.autocommit = False

    db_module.engine = engine
    with tenant.system():
        db_module._seed_exercise_library()
        db_module._seed_workout_examples()
    print("seeded")


def _secret_owners() -> list[str]:
    if not settings.is_public:
        return [tenant.PERSONAL_OWNER]
    from catch.api.routes_internal import user_ids

    return user_ids()


def cmd_secrets_status(args: argparse.Namespace) -> None:
    from collections import Counter

    from catch.core import secret_store
    from catch.sync import secret_rotation

    init_db()
    total: Counter = Counter()
    for owner in _secret_owners():
        with tenant.use_owner(owner), get_session() as session:
            total.update(secret_rotation.status(session))
    current = secret_store.current_key_id()
    print(f"current master id: {current}")
    for key_id, n in sorted(total.items()):
        print(f"  sealed under {key_id}{' (current)' if key_id == current else ' (OLD — run `catch secrets rotate`)'}: {n}")
    if not total:
        print("  no sealed credentials")


def cmd_secrets_rotate(args: argparse.Namespace) -> None:
    from catch.sync import secret_rotation

    init_db()
    resealed = skipped = 0
    failed: list[str] = []
    for owner in _secret_owners():
        with tenant.use_owner(owner), get_session() as session:
            report = secret_rotation.rotate_owner(session, dry_run=args.dry_run)
        resealed += report["resealed"]
        skipped += report["already_current"]
        failed += [f"{owner[:8]}…/{item}" for item in report["failed"]]
    print(("dry run — would re-seal " if args.dry_run else "re-sealed ") + f"{resealed}; already current: {skipped}")
    if failed:
        print("could not open (is the previous master still in CATCH_SECRETS_MASTER_KEY_PREVIOUS?): " + ", ".join(failed))
        raise SystemExit(1)


def cmd_export_personal(args: argparse.Namespace) -> None:
    from pathlib import Path

    from catch.sync import personal_transfer

    if settings.is_public:
        raise SystemExit("export-personal reads the personal SQLite database; run it on the Pi (CATCH_DEPLOYMENT=personal).")
    init_db()
    with get_session() as session:
        manifest = personal_transfer.export_personal(session, Path(args.out))
    print(f"wrote {args.out}")
    for table, n in manifest["counts"].items():
        if n:
            print(f"  {table}: {n}")
    print("not exported:", ", ".join(manifest["excluded"]))


def cmd_import_personal(args: argparse.Namespace) -> None:
    from pathlib import Path

    from catch.sync import personal_transfer

    if not settings.is_public:
        raise SystemExit("import-personal writes to a public account; set CATCH_DEPLOYMENT=public and DATABASE_URL.")
    try:
        with tenant.use_owner(args.user_id), get_session() as session:
            report = personal_transfer.import_into_account(session, Path(args.file), owner_id=args.user_id, dry_run=args.dry_run)
    except personal_transfer.ImportRefused as exc:
        raise SystemExit(f"refused: {exc}") from None
    print(("dry run — nothing written" if args.dry_run else "imported") + f" as {args.user_id}")
    for table, n in report["imported"].items():
        print(f"  {table}: {n}")
    if not args.dry_run:
        print("Now run: the app recomputes recovery and strain on the next sync; or call POST /api/settings once.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="catch")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_parser = sub.add_parser("sync", help="Sync one source")
    sync_parser.add_argument("--source", required=True, choices=["garmin", "withings", "concept2", "whoop"])
    sync_parser.add_argument("--days", type=int, default=3)
    sync_parser.set_defaults(func=cmd_sync)

    backfill_parser = sub.add_parser("backfill", help="Backfill all sources")
    backfill_parser.add_argument("--days", type=int, default=None)
    backfill_parser.set_defaults(func=cmd_backfill)

    whoop_parser = sub.add_parser("whoop", help="Whoop utilities")
    whoop_sub = whoop_parser.add_subparsers(dest="whoop_command", required=True)
    whoop_sub.add_parser("check", help="Manual connection test (counts only, no secrets printed)").set_defaults(func=cmd_whoop_check)

    gps_parser = sub.add_parser("backfill-gps", help="Parse GPS tracks from stored FIT files (and weather)")
    gps_parser.add_argument("--weather", action="store_true", help="also fetch weather for each track")
    gps_parser.add_argument("--force", action="store_true", help="re-parse tracks that already exist")
    gps_parser.set_defaults(func=cmd_backfill_gps)

    token_parser = sub.add_parser("token", help="Manage device bearer tokens (for the MCP server)")
    token_sub = token_parser.add_subparsers(dest="token_command", required=True)
    token_create_parser = token_sub.add_parser("create", help="Create a new device token")
    token_create_parser.add_argument("--name", required=True)
    token_create_parser.add_argument("--role", choices=["athlete", "coach"], default="athlete", help="coach tokens reach only the workout-library/technique-note/feedback tools")
    token_create_parser.add_argument("--display-name", default=None, help="the name shown on a coach token's feedback entries")
    token_create_parser.set_defaults(func=cmd_token_create)
    token_list_parser = token_sub.add_parser("list", help="List device tokens")
    token_list_parser.set_defaults(func=cmd_token_list)

    db_parser = sub.add_parser("db", help="Public (Supabase Postgres) database operations")
    db_sub = db_parser.add_subparsers(dest="db_command", required=True)
    up = db_sub.add_parser("upgrade", help="Apply Alembic migrations (needs DATABASE_ADMIN_URL)")
    up.add_argument("revision", nargs="?", default="head")
    up.set_defaults(func=cmd_db_upgrade)
    db_sub.add_parser("check", help="Role, SSL and row-level-security probe over the runtime connection").set_defaults(func=cmd_db_check)
    db_sub.add_parser("current", help="Applied vs expected migration revision (needs DATABASE_ADMIN_URL)").set_defaults(func=cmd_db_current)
    db_sub.add_parser("seed", help="Seed global reference data (needs DATABASE_ADMIN_URL)").set_defaults(func=cmd_db_seed)

    secrets_parser = sub.add_parser("secrets", help="Master-key rotation for sealed credentials (docs/security.md)")
    secrets_sub = secrets_parser.add_subparsers(dest="secrets_command", required=True)
    secrets_sub.add_parser("status", help="How many sealed credentials are on each master key").set_defaults(func=cmd_secrets_status)
    rotate_parser = secrets_sub.add_parser("rotate", help="Re-seal every credential under the current master key")
    rotate_parser.add_argument("--dry-run", action="store_true")
    rotate_parser.set_defaults(func=cmd_secrets_rotate)

    exp = sub.add_parser("export-personal", help="Write the personal install's data to a file for a public account (docs/personal-to-public.md)")
    exp.add_argument("--out", required=True)
    exp.set_defaults(func=cmd_export_personal)
    imp = sub.add_parser("import-personal", help="Import that file into a new, empty public account (as that user)")
    imp.add_argument("--file", required=True)
    imp.add_argument("--user-id", required=True, help="the Supabase user id of the account (it must have signed in once)")
    imp.add_argument("--dry-run", action="store_true")
    imp.set_defaults(func=cmd_import_personal)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
