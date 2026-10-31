from __future__ import annotations

import argparse

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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
