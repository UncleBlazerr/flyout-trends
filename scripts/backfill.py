"""Backfill historical dates into the store (oldest first), without touching
the site. Each date runs the exact same ingest+score+write path as the daily
pipeline; re-running a date rewrites it in full.

Usage:
    python scripts/backfill.py --days 2                 # last N days ending yesterday ET
    python scripts/backfill.py --start 2026-06-05 --end 2026-07-04
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hr_tracker.ingest import ingest_date
from hr_tracker.models import find_config
from hr_tracker.scoring import score_events
from hr_tracker.store import FlatFileStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill historical dates")
    parser.add_argument("--days", type=int, default=None,
                        help="Backfill the last N days ending at --end")
    parser.add_argument("--start", default=None, help="First date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None,
                        help="Last date (YYYY-MM-DD); defaults to yesterday ET")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument("--sleep", type=float, default=1.0,
                        help="Seconds to pause between dates (be polite)")
    args = parser.parse_args()

    end = date_cls.fromisoformat(args.end) if args.end else (
        datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1))
    if args.start:
        start = date_cls.fromisoformat(args.start)
    elif args.days:
        start = end - timedelta(days=args.days - 1)
    else:
        parser.error("provide --days or --start")
    if start > end:
        parser.error("start is after end")

    config = find_config(args.config)
    root = Path(__file__).resolve().parent.parent
    storage = config["storage"]
    store = FlatFileStore(root / storage["raw_dir"], root / storage["rollup_dir"])

    failed_dates = []
    d = start
    while d <= end:
        date = d.isoformat()
        print(f"[backfill] {date} ...", file=sys.stderr)
        events, summary = ingest_date(date, config)
        events = score_events(events, config)
        store.write_day(date, events)
        print(f"[backfill] {date}: {summary['games_processed']} games, "
              f"{len(events)} batted balls"
              + (f", FAILED pks {summary['games_failed']}"
                 if summary["games_failed"] else ""), file=sys.stderr)
        if summary["games_failed"]:
            failed_dates.append(date)
        d += timedelta(days=1)
        if d <= end:
            time.sleep(args.sleep)

    if failed_dates:
        print(f"[backfill] dates with failed games: {failed_dates}", file=sys.stderr)
        return 1
    print(f"[backfill] done: {start} .. {end}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
