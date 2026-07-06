---
name: hr-proximity
description: Fetch and score a date's MLB batted-ball events for HR proximity (near-home-run signal). Use when asked to check near-HR candidates, HR-proximity trends, which hitters are "heating up", or who is most likely to homer next (defaults to today ET).
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
- Prints JSON to stdout: `summary` (games processed/skipped/failed),
  `near_hr_events` sorted by `barrel_score` descending, and `predictions` —
  the ranked "most likely to homer" grouping computed from already-stored
  history (a dry run never writes, so the freshly fetched day is not in it).
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
recomputes 7/14/30-day trends, writes the day's prediction receipt to
`data/predictions/<date>.json`, and rebuilds the static dashboard in `docs/`.

## HR expectancy ("most likely to homer")

`hr_tracker/prediction.py` ranks active hitters by a 0–100 expectancy score:
streak of consecutive games with a near-HR event + how often recent games
qualify + rising intensity slopes (max EV, would-be-HR parks, near-HR count).
Alongside it, an empirical band rate measured from this repo's own history
(how often an HR followed within `prediction.horizon_days` for player-days in
the same score band; hidden below `prediction.min_samples` samples). Read the
current grouping from `docs/data/predictions.json` after any full run, or:

```python
from hr_tracker.prediction import compute_predictions
preds = compute_predictions(store, "2026-07-05", config)
```

Near-HR doubles/triples weigh more than outs (`prediction.xbh_weight`); each
entry carries informational `hr_7d`, `max_ev_7d`, `max_distance_7d`,
`near_hr_xbh_7d`, and `repeat` (also flagged on the previous pull). The model
cross-checks itself every run: `recent_hits` in `predictions.json` lists
flagged players who have since homered, and past receipts resolve into a
track record via
`resolve_prediction_records("data/predictions", store.read_player_days(), config)`.
Knobs live in `config.yaml` (`prediction` section).

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
