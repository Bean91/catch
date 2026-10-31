from __future__ import annotations

import argparse
from datetime import date, timedelta

from catch.core.config import settings
from catch.core.db import get_session, init_db
from catch.sync.scheduler import FIT_DIR
from catch.sync import state


def cmd_sync(args: argparse.Namespace) -> None:
    init_db()
    with get_session() as session:
        state.record_attempt(session, args.source)
        try:
            if args.source == "garmin":
                from catch.sync.garmin_client import GarminClient

                client = GarminClient(session)
                end = date.today()
                start = end - timedelta(days=args.days)
                health_rows = client.sync_health(start, end)
                activities = client.sync_activities(start, end, FIT_DIR)
                print(f"garmin: {health_rows} daily_wellness rows, {activities} activities")
            elif args.source == "withings":
                from catch.sync.withings_client import sync as withings_sync

                n = withings_sync(session, days=args.days)
                print(f"withings: {n} body_comp rows")
            else:
                raise SystemExit(f"unknown source: {args.source}")
            state.record_success(session, args.source)
        except Exception as exc:
            state.record_error(session, args.source, str(exc))
            raise


def cmd_backfill(args: argparse.Namespace) -> None:
    init_db()
    days = args.days or settings.backfill_days
    with get_session() as session:
        for source in ("garmin", "withings"):
            state.record_attempt(session, source)
            try:
                if source == "garmin":
                    from catch.sync.garmin_client import GarminClient

                    totals = GarminClient(session).backfill(days, FIT_DIR)
                    print(f"garmin backfill ({days}d): {totals}")
                else:
                    from catch.sync.withings_client import sync as withings_sync

                    n = withings_sync(session, days=days)
                    print(f"withings backfill ({days}d): {n} body_comp rows")
                state.record_success(session, source)
            except Exception as exc:
                state.record_error(session, source, str(exc))
                print(f"{source} backfill failed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="catch")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_parser = sub.add_parser("sync", help="Sync one source")
    sync_parser.add_argument("--source", required=True, choices=["garmin", "withings"])
    sync_parser.add_argument("--days", type=int, default=3)
    sync_parser.set_defaults(func=cmd_sync)

    backfill_parser = sub.add_parser("backfill", help="Backfill all sources")
    backfill_parser.add_argument("--days", type=int, default=None)
    backfill_parser.set_defaults(func=cmd_backfill)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
