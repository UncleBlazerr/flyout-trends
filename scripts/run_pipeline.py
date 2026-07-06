"""CLI entrypoint used by both the GitHub Actions workflow and local/skill runs.

Usage:
    python scripts/run_pipeline.py                  # today (ET), full pipeline
    python scripts/run_pipeline.py --date 2026-07-03
    python scripts/run_pipeline.py --dry-run        # ingest+score, print, no writes
    python scripts/run_pipeline.py --include-unfinished
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hr_tracker.ingest import ingest_date
from hr_tracker.models import find_config
from hr_tracker.prediction import (annotate_repeats, compute_predictions,
                                   cross_check, resolve_prediction_records,
                                   write_prediction_record)
from hr_tracker.scoring import score_events
from hr_tracker.site import build_site
from hr_tracker.store import FlatFileStore
from hr_tracker.trends import compute_trends


def today_et() -> str:
    """MLB's 'day' runs on US Eastern time."""
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="HR-Proximity Tracker pipeline")
    parser.add_argument("--date", default=None,
                        help="Date to process (YYYY-MM-DD); defaults to today ET")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="Ingest + score and print JSON to stdout; write nothing")
    parser.add_argument("--include-unfinished", action="store_true",
                        help="Also ingest games that are not Final yet")
    parser.add_argument("--skip-site", action="store_true",
                        help="Persist data but do not rebuild the site")
    args = parser.parse_args()

    date = args.date or today_et()
    config = find_config(args.config)

    print(f"[ingest] fetching schedule + gamefeeds for {date} ...", file=sys.stderr)
    events, summary = ingest_date(date, config,
                                  include_unfinished=args.include_unfinished)
    events = score_events(events, config)
    near = [e for e in events if e.is_near_hr]
    print(f"[ingest] {summary['games_processed']}/{summary['games_scheduled']} games "
          f"final+processed, {len(events)} batted balls, {len(near)} near-HR",
          file=sys.stderr)
    if summary["games_skipped_not_final"]:
        print(f"[ingest] skipped (not final): {summary['games_skipped_not_final']}",
              file=sys.stderr)
    if summary["games_failed"]:
        print(f"[ingest] FAILED game_pks: {summary['games_failed']}", file=sys.stderr)

    root = Path(__file__).resolve().parent.parent
    storage = config["storage"]
    store = FlatFileStore(root / storage["raw_dir"], root / storage["rollup_dir"])

    if args.dry_run:
        # Predictions read only already-stored history; today's (unwritten)
        # events don't affect them in a dry run.
        out = {"summary": summary,
               "near_hr_events": [e.to_dict() for e in
                                  sorted(near, key=lambda e: e.barrel_score,
                                         reverse=True)],
               "predictions": compute_predictions(store, date, config)}
        print(json.dumps(out, indent=2))
        return 0

    store.write_day(date, events)
    print(f"[store] wrote {storage['raw_dir']}/{date}.json + player index",
          file=sys.stderr)

    trends = compute_trends(store, date, config)
    print(f"[trends] computed rolling stats for {len(trends['players'])} players",
          file=sys.stderr)

    predictions = compute_predictions(store, date, config)
    records_dir = root / config["prediction"]["records_dir"]
    predictions = annotate_repeats(predictions, records_dir)
    record = write_prediction_record(records_dir, predictions, config)
    player_days = store.read_player_days()
    hit_rate = resolve_prediction_records(records_dir, player_days, config)
    recent_hits = cross_check(records_dir, player_days, config, date)
    print(f"[predict] {len(predictions['players'])} players flagged; "
          f"record {record.name}; {len(recent_hits)} recent flags converted"
          + (f"; hit rate {hit_rate['overall']['rate']}" if hit_rate else ""),
          file=sys.stderr)

    if not args.skip_site:
        config["site"]["output_dir"] = str(root / config["site"]["output_dir"])
        index = build_site(events, trends, date, summary, config,
                           predictions=predictions, hit_rate=hit_rate,
                           recent_hits=recent_hits)
        print(f"[site] rebuilt {index}", file=sys.stderr)

    return 1 if summary["games_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
