# Daily HR-Proximity Tracker

Surfaces MLB hitters who are squaring the ball up and trending toward a home
run before it shows up in box scores. Twice a day it ingests every game's
Statcast batted-ball data from Baseball Savant, classifies each event against
three near-HR definitions, persists an append-only dataset, computes rolling
7/14/30-day per-player trends, and publishes a static dashboard via GitHub
Pages.

## Near-HR definitions (all three computed per event)

1. **Distance threshold** — non-HR result (flyout/lineout/single/double)
   traveling farther than `near_hr.distance.threshold_ft` (default 350 ft).
2. **Park-adjusted would-be-HR** — Savant's `contextMetrics.homeRunBallparks`:
   in how many of the 30 parks that ball is a home run. A non-HR clearing
   `near_hr.would_be_hr.min_parks` is flagged. (The PRD scoped this as a
   park-dimensions research spike; Savant turns out to publish the number
   directly in the gamefeed, so it's exact, not approximate.)
3. **Composite barrel-proximity score** — 0–100 weighted blend of exit
   velocity, launch-angle deviation from 27.5°, and distance.

All thresholds/weights live in `config.yaml`.

## HR expectancy ("Most likely to homer")

Near-misses that persist day over day are the signal: `hr_tracker/prediction.py`
tracks each player's **streak** of consecutive games with a near-HR event
(rest-day gaps up to `prediction.max_gap_days` don't break it), how *often*
recent games qualify, and whether the underlying quality is intensifying
(rising slopes of max EV, would-be-HR parks, and near-HR frequency). These
blend into a 0–100 **expectancy score** whose weights live under `prediction:`
in `config.yaml`.

Alongside the heuristic score, an **empirical rate table** is measured from
this repo's own stored history: of all past player-days scoring in the same
band, how often did an HR actually follow within `prediction.horizon_days`?
It's shown once a band has `prediction.min_samples` samples and self-calibrates
as data accumulates.

Each full pipeline run writes an append-only receipt of the day's flagged
players to `data/predictions/YYYY-MM-DD.json`. Once a receipt is older than
the horizon, it is resolved against actual outcomes and the dashboard shows
the running track record ("X of Y flagged players homered within 3 days").

## Layout

```
hr_tracker/         importable package (used by workflow AND skill — one code path)
  models.py         BattedBallEvent, config loading
  ingest.py         MLB schedule + Savant /gf fetch + parse
  scoring.py        the three near-HR metrics (pure functions)
  store.py          EventStore protocol + FlatFileStore (v1)
  trends.py         rolling 7/14/30-day per-player stats
  prediction.py     streaks, expectancy score, empirical rates, receipts
  site.py           static HTML/JSON dashboard generator
scripts/run_pipeline.py   CLI entrypoint (workflow, local, and skill runs)
scripts/backfill.py       ingest a historical date range (oldest first)
config.yaml         thresholds, weights, windows
data/raw/           one immutable JSON per date (schema_version inside)
data/rollups/       player_index.json incremental rollup
data/predictions/   daily receipts of flagged players (append-only)
docs/               GitHub Pages source (generated, committed)
.claude/skills/hr-proximity/SKILL.md   Claude Code Skill for ad hoc runs
.claude/agents/savant-analyst.md   Baseball Savant analyst subagent
.github/workflows/hr-tracker.yml   cron (06:00 + 23:00 ET) + workflow_dispatch
```

## Usage

```bash
pip install -r requirements.txt
python scripts/run_pipeline.py                    # today (ET), full pipeline
python scripts/run_pipeline.py --date 2026-07-03  # backfill a specific date
python scripts/run_pipeline.py --dry-run          # print scored events, no writes
```

Only Final games are ingested by default (`--include-unfinished` to override),
so re-running a date before all games finish simply picks up the newly-final
games; each run rewrites that date's file in full.

View the dashboard locally: `python -m http.server -d docs 8000` →
http://localhost:8000. On GitHub, enable Pages with source "Deploy from a
branch", branch `main`, folder `/docs`.

## Storage & migration path

Everything reads/writes through the `EventStore` protocol (`store.py`). To
move to SQLite/Postgres later, implement the protocol and replay each
`data/raw/*.json` through `write_day()` — no other component changes.

## Tests

```bash
python -m pytest
```
