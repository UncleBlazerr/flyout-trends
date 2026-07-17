---
type: Architecture
title: Architecture
description: Pipeline architecture for the Daily HR-Proximity Tracker — linear data pipeline with one CLI entrypoint, module-per-stage design, and shared code path for Actions, local, and agent runs.
tags: [architecture, pipeline, modules, design]
---

# Architecture

The project is a linear data pipeline: each stage is one Python module, orchestrated by a single CLI entrypoint. The same code path runs in GitHub Actions, locally, and via agent skills — no duplicated logic.

## Pipeline stages

```
ingest → score → store → trends → predict → weather → site
```

| Stage | Module | Responsibility |
|---|---|---|
| Ingest | `hr_tracker/ingest.py` | Fetch MLB schedule + Savant gamefeeds, parse batted-ball events |
| Score | `hr_tracker/scoring.py` | Attach three near-HR classifications to each event (pure functions) |
| Store | `hr_tracker/store.py` | Persist per-date JSON + maintain player-index rollup |
| Trends | `hr_tracker/trends.py` | Rolling 7/14/30-day per-player stats, slope, `heating_up` flag |
| Predict | `hr_tracker/prediction.py` | Streaks, expectancy score, weather factor, empirical rates, prediction receipts |
| Weather | `hr_tracker/weather.py` | League-wide HR-vs-weather correlation table (temp × wind cells) |
| Site | `hr_tracker/site.py` | Generate static HTML + JSON dashboard in `docs/` |

All stages are orchestrated by `scripts/run_pipeline.py`, which is the **single
entry point** for the GitHub Actions workflow, local runs, agent skills, and
the Hermes daily run.

## Module details

### `hr_tracker/models.py`
- `BattedBallEvent` dataclass: the core data unit, carrying raw fields (EV,
  launch angle, distance, `would_be_hr_count`) and scoring outputs
  (`distance_flag`, `would_be_hr_flag`, `barrel_score`, `barrel_flag`).
- `load_config()` / `find_config()`: load `config.yaml` from the repo root.
- `SCHEMA_VERSION = 2`: stamped into every stored file (raw + rollup). v2 adds
  venue/weather context to events and rollup days.
- `is_home_run` and `is_near_hr` are computed properties, not stored fields.
- In addition to raw Savant fields, the dataclass carries game-level
  `venue_id`, `venue_name`, `temp_f`, `wind_mph`, `wind_dir`, and
  `weather_condition` — attached by `ingest.py` from the MLB schedule API
  (Savant has no weather). All default to None/"" so old JSON still loads.

### `hr_tracker/ingest.py`
- `fetch_schedule(date, session, http_cfg)`: queries the MLB Stats API
  (`statsapi.mlb.com/api/v1/schedule`) for all games on a date.
- `fetch_gamefeed(game_pk, session, http_cfg)`: fetches the Savant gamefeed
  (`baseballsavant.mlb.com/gf?game_pk=`).
- `parse_events(gamefeed, date)`: parses the `exit_velocity[]` array into
  `BattedBallEvent` objects. Only `pitch_call == "hit_into_play"` rows with a
  measured exit velocity are kept. Events are deduplicated by `play_id`.
- `ingest_date(date, config, ...)`: orchestrates fetch + parse, returning
  `(events, summary)`. By default only Final games (statusCode `F`/`O`) are
  ingested so in-progress games never pollute a day file.
- **Weather ingest**: `fetch_schedule` sends `hydrate=weather`, returning
  per-game `condition`/`temp`/`wind` in one slate-wide call. `parse_wind()`
  maps the park-relative wind phrase to a direction class (`out`/`in`/`cross`/
  `none`/`varies`; unrecognized → `varies`). `_attach_weather()` stamps venue
  and weather fields onto each game's events inside `ingest_date`. If a final
  game's schedule weather object is empty, `fetch_live_weather()` falls back to
  that game's live feed (`statsapi.mlb.com/api/v1.1/game/<pk>/feed/live` with
  `fields=` trim). Missing weather stays None/"" — never guessed.
- **Savant gotcha**: numeric fields (`launch_speed`, `hit_distance`,
  `launch_angle`) arrive as strings. All parsing goes through the `_num()`
  helper. `hc_x`/`hc_y` arrive as floats.
- `contextMetrics.homeRunBallparks` is the exact park-adjusted would-be-HR
  count (0–30) — no separate park-dimensions dataset is needed.
- HTTP calls use retry with exponential backoff (configured in `config.yaml` →
  `http`).

### `hr_tracker/scoring.py`
Pure functions — no I/O, no side effects. See
[Scoring & Prediction](scoring-and-prediction.md) for the definitions.

### `hr_tracker/store.py`
`EventStore` is a `Protocol` with four methods: `write_day`, `read_range`,
`read_player_history`, `read_player_days`. `FlatFileStore` is the v1
implementation; `_update_rollup` writes `temp_f`/`wind_mph`/`wind_dir` per
player-day (schema v2). See [Data & Storage](data-and-storage.md).

### `hr_tracker/trends.py`
- `linear_slope(ys)`: least-squares slope — the trend engine used by both
  trends and prediction intensity.
- `compute_trends(store, as_of, config)`: iterates all players active in the
  max trailing window, computes per-window stats, classifies trend direction
  (`rising` / `falling` / `flat`), and sets the `heating_up` flag.
- Players are sorted by near-HR count (descending) within the heating-up
  window, then by max barrel score.

### `hr_tracker/prediction.py`
Reads the rollup via `store.read_player_days()` — never re-scans raw event
files. Ranks players by a weather-adjusted expectancy score
(`adjusted_score = expectancy_score × weather_factor`), where
`weather_factor` is a multiplier derived from each player's upcoming game
forecast (temperature + wind). The base `expectancy_score` still drives the
empirical band labels and self-check so historical calibration is not
distorted. `ingest.upcoming_team_weather()` fetches the next-day slate's
weather to supply the factor. See [Scoring & Prediction](scoring-and-prediction.md).

### `hr_tracker/weather.py`
`weather_correlation(player_days, config)`: buckets every rollup player-day
into temperature-band × wind-class cells (plus a dome/roof-closed row) and
computes HR-day rate, near-HR-day rate, and near-HR→HR follow-through within
`horizon_days`. Rates hide behind `prediction.weather.min_samples`. This
table justifies (or refutes) the `weather_factor` rule-of-thumb weights.

### `hr_tracker/site.py`
- `build_site(...)`: writes `docs/index.html`, `docs/player.html`, and JSON
  payloads under `docs/data/`.
- HTML/CSS/JS are embedded as Python string constants (`INDEX_HTML`,
  `PLAYER_HTML`) — no templating engine, no build step.
- `_write_player_pages(...)`: writes one JSON per active player with their
  day-by-day rollup, current form, and every tracked batted ball.

## Config system (`config.yaml` + `hr_tracker/models.py`)

All tunable parameters live in `config.yaml` at the repo root. The package
locates it via `find_config()`, which resolves the repo root relative to the
package directory. Never hardcode thresholds or weights — always read from
config.

Key sections:
- `near_hr` — distance threshold, would-be-HR min parks, barrel score weights
- `trends` — trailing windows, heating-up thresholds, flat-slope cutoff
- `prediction` — expectancy weights, intensity scales, score bands, horizon, records dir, weather factor config
- `site` — title, output directory
- `storage` — raw and rollup directories
- `http` — timeout, retries, backoff

## Design principles

1. **One entry point**: `scripts/run_pipeline.py` is used by the workflow,
   local development, skills, and the agent. Keep it the single path — never
   duplicate pipeline logic.
2. **Config-driven**: all thresholds, weights, and windows live in
   `config.yaml`. Never hardcode tuning values in source.
3. **Protocol-based storage**: every component talks to `EventStore`, not to
   files directly. Swapping to SQLite/Postgres means implementing the protocol
   and replaying `data/raw/*.json`.
4. **Immutable date files**: re-running a date rewrites that date's file in
   full. Other dates are never touched.
5. **Append-only prediction receipts**: `data/predictions/YYYY-MM-DD.json` are
   never edited for past dates — they are the model's track record.
