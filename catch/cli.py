from __future__ import annotations

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
        for source in SOURCES:
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="catch")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_parser = sub.add_parser("sync", help="Sync one source")
    sync_parser.add_argument("--source", required=True, choices=["garmin", "withings", "concept2"])
    sync_parser.add_argument("--days", type=int, default=3)
    sync_parser.set_defaults(func=cmd_sync)

    backfill_parser = sub.add_parser("backfill", help="Backfill all sources")
    backfill_parser.add_argument("--days", type=int, default=None)
    backfill_parser.set_defaults(func=cmd_backfill)

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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
