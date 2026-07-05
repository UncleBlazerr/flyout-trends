---
name: hr-proximity
description: Fetch and score a date's MLB batted-ball events for HR proximity (near-home-run signal). Use when asked to check near-HR candidates, HR-proximity trends, or which hitters are "heating up" for a given date (defaults to today ET).
---

# HR-Proximity check

Runs the exact same ingestion + scoring code the scheduled GitHub Actions
workflow uses (the `hr_tracker` package in this repo) — no duplicated logic.

## On-demand scored events (no writes)

From the repo root:

```
python scripts/run_pipeline.py --dry-run [--date YYYY-MM-DD]
```

- Defaults to **today in US Eastern time** (MLB's calendar day) when `--date`
  is omitted.
- Prints JSON to stdout: `summary` (games processed/skipped/failed) and
  `near_hr_events`, sorted by `barrel_score` descending.
- Only games with Final status are ingested; add `--include-unfinished` to
  peek at in-progress games (data will be partial).

Each event carries all three near-HR classifications:

| Field | Meaning |
|---|---|
| `distance_flag` | Non-HR result (flyout/lineout/single/double) beyond the config distance threshold |
| `would_be_hr_count` / `would_be_hr_flag` | Park-adjusted count of parks (0-30) where the ball is a HR (from Savant's `contextMetrics.homeRunBallparks`); flagged when a non-HR clears `min_parks` |
| `barrel_score` / `barrel_flag` | Composite 0-100 blend of exit velocity, launch-angle deviation from 27.5°, and distance |

Thresholds/weights live in `config.yaml` (`near_hr` section).

## Full pipeline (persist + trends + site)

```
python scripts/run_pipeline.py [--date YYYY-MM-DD]
```

Writes `data/raw/<date>.json`, updates `data/rollups/player_index.json`,
recomputes 7/14/30-day trends, and rebuilds the static dashboard in `docs/`.

## Reading historical trends

Trend data (rolling 7/14/30-day near-HR counts, EV stats, slope, `heating_up`
flag per player) is in `docs/data/trends.json` after any full run, or compute
programmatically:

```python
from hr_tracker.models import find_config
from hr_tracker.store import FlatFileStore
from hr_tracker.trends import compute_trends

config = find_config()
store = FlatFileStore("data/raw", "data/rollups")
trends = compute_trends(store, "2026-07-04", config)
```
