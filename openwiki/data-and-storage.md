---
type: Data Model
title: Data & Storage
description: Data flow and storage model for the Daily HR-Proximity Tracker — raw per-date JSON files, player index rollup, prediction receipts, EventStore protocol, and published dashboard JSON.
tags: [data, storage, json, schema, eventstore]
---

# Data & Storage

How data flows through the system: raw files → player rollup → prediction
receipts → published dashboard JSON.

## Data flow

```
Baseball Savant API
    ↓
data/raw/YYYY-MM-DD.json          ← immutable per-date event files
    ↓
data/rollups/player_index.json   ← incremental per-player per-day rollup
    ↓
data/predictions/YYYY-MM-DD.json ← append-only prediction receipts
    ↓
docs/data/*.json + docs/data/players/*.json  ← published dashboard data
docs/index.html + docs/player.html           ← static HTML
```

All reads and writes go through the `EventStore` protocol
(`hr_tracker/store.py`). No other component touches files directly.

## EventStore protocol

Defined in `hr_tracker/store.py` as a Python `Protocol`:

| Method | Purpose |
|---|---|
| `write_day(date, events)` | Write a full day's events; re-running a date replaces it |
| `read_range(start, end)` | Read all events across a date range |
| `read_player_history(player_id, days, end)` | Read one player's events within a trailing window |
| `read_player_days()` | Read the per-player per-day rollup (used by trends + prediction) |

`FlatFileStore` is the v1 implementation. To migrate to SQLite/Postgres,
implement the protocol and replay each `data/raw/*.json` through `write_day()`
— no other component changes.

## `write_day` semantics

- Writes the full day's events to `data/raw/<date>.json`. Re-running a date
  rewrites that file **in full** (never appends); other dates are never touched.
- Then updates `player_index.json`: drops that date's per-player entries
  before re-adding them, so the rollup always matches the raw files.
- Prunes players whose every day was removed (no orphan entries).

## File formats

### `data/raw/YYYY-MM-DD.json`

One file per date. Contains every batted-ball event from all Final games that
day.

```json
{
  "schema_version": 2,
  "date": "2026-07-05",
  "generated_at": "2026-07-05T14:23:00Z",
  "events": [ { ...BattedBallEvent.to_dict()... } ]
}
```

### `data/rollups/player_index.json`

Incremental per-player per-day summary, updated on every `write_day`. This is
what trends and prediction read — they never re-scan raw event files.

```json
{
  "schema_version": 2,
  "players": {
    "695578": {
      "player_name": "James Wood",
      "team": "WSH",
      "days": {
        "2026-07-05": {
          "bbe": 4, "hr": 0,
          "near_hr_any": 2, "near_hr_xbh": 1,
          "near_hr_distance": 1, "near_hr_parks": 2, "near_hr_barrel": 1,
          "would_be_hr_parks_sum": 14,
          "max_ev": 109.3, "max_distance": 391.0, "max_barrel_score": 82.5,
          "temp_f": 89.0, "wind_mph": 5.0, "wind_dir": "out",
          "weather_condition": "Clear"
        }
      }
    }
  }
}
```

Rollup day fields:

| Field | Meaning |
|---|---|
| `bbe` | Batted-ball events count |
| `hr` | Home runs |
| `near_hr_any` | Events flagged by any near-HR definition |
| `near_hr_xbh` | Near-HR events that were doubles/triples |
| `near_hr_distance` | Distance flag count |
| `near_hr_parks` | Would-be-HR flag count |
| `near_hr_barrel` | Barrel flag count |
| `would_be_hr_parks_sum` | Sum of `homeRunBallparks` across non-HR events |
| `max_ev` | Max exit velocity |
| `max_distance` | Max hit distance |
| `max_barrel_score` | Max barrel score |
| `temp_f` | Game temperature (°F) — from schedule weather, first event's value wins |
| `wind_mph` | Wind speed (mph) — from schedule weather |
| `wind_dir` | Wind direction class: `out`/`in`/`cross`/`none`/`varies` |
| `weather_condition` | Weather condition text (e.g. "Clear", "Dome") — from schedule weather |

**Note:** Rollup days written before the `near_hr_any` field existed are
handled by the `_near_hr_any()` fallback in `prediction.py`, which reconstructs
it from the per-definition counts (capped at `bbe`).

### `data/predictions/YYYY-MM-DD.json`

Append-only receipts of flagged players. Each entry is a full form snapshot at
prediction time. These are the model's track record — never edit past dates
manually. Re-running a date supersedes that date's record.

```json
{
  "schema_version": 2,
  "generated_at": "...",
  "as_of": "2026-07-05",
  "config": { ...prediction config snapshot... },
  "players": [ { ...expectancy score, streak, slopes, band... } ]
}
```

### `docs/data/` (published dashboard data)

Written by `build_site()` in `hr_tracker/site.py`, consumed by the frontend at
runtime:

| File | Contents |
|---|---|
| `latest.json` | Today's near-HR events with full metrics |
| `meta.json` | Date, game counts, event totals |
| `trends.json` | Rolling 7/14/30-day per-player stats |
| `predictions.json` | Most-Likely list + empirical bands + hit rate + recent hits |
| `consistency.json` | Consistency leaderboard |
| `analysis.json` | LLM-written daily blurb (written by Hermes, shown while `as_of` matches) |
| `weather.json` | League-wide HR-vs-weather correlation table (temp × wind cells + dome row) |
| `players/<player_id>.json` | Per-player: form, day-by-day rollup, every tracked batted ball |

## BattedBallEvent dataclass

The core data unit (`hr_tracker/models.py`):

| Field | Type | Source |
|---|---|---|
| `game_pk` | int | MLB game ID |
| `date` | str | YYYY-MM-DD |
| `player_id` | int | MLB player ID |
| `player_name` | str | From Savant |
| `team` / `opponent` | str | Batting / fielding team |
| `result` | str | e.g. "Flyout", "Home Run", "Double" |
| `exit_velocity` | float? | Savant `launch_speed` (parsed from string) |
| `launch_angle` | float? | Savant `launch_angle` (parsed from string) |
| `hit_distance` | float? | Savant `hit_distance` (parsed from string) |
| `hc_x` / `hc_y` | float? | Spray chart coordinates |
| `would_be_hr_count` | int? | `contextMetrics.homeRunBallparks` (0–30) |
| `inning` | int? | Inning number |
| `play_id` | str? | Deduplication key |
| `venue_id` | int? | MLB venue ID (from schedule weather hydration) |
| `venue_name` | str | Venue name (empty when feed omitted weather) |
| `temp_f` | float? | Game temperature °F (from schedule weather) |
| `wind_mph` | float? | Wind speed mph (from schedule weather) |
| `wind_dir` | str? | Wind class: `out`/`in`/`cross`/`none`/`varies` |
| `weather_condition` | str | Weather condition text (e.g. "Clear", "Dome") |
| `distance_flag` | bool | Set by `scoring.py` |
| `would_be_hr_flag` | bool | Set by `scoring.py` |
| `barrel_score` | float | Set by `scoring.py` |
| `barrel_flag` | bool | Set by `scoring.py` |

Computed properties: `is_home_run` (result == "Home Run"), `is_near_hr` (any
of the three flags).

## Storage rules

1. **Only Final games are ingested** by default (statusCode `F`/`O`) so
   in-progress games never pollute a day file.
2. **Near-HR flags exclude actual home runs** — an HR is not "near" an HR.
3. **Re-running a date** rewrites that date's raw file and rollup entries in
   full. Other dates are untouched.
4. **Prediction receipts are append-only** — `resolve_prediction_records`
   measures the model's real hit rate from them. Never rewrite old ones (except
   by re-running that date's pipeline).
5. **All prediction math** reads the rollup via `store.read_player_days()`.
   Rollup days written before the `near_hr_any` field existed are handled by
   the `_near_hr_any` fallback in `prediction.py`.

## Savant feed parsing notes

- Numeric fields arrive as **strings** (`"113.1"`, `"428"`); `hc_x`/`hc_y` are
  floats. All parsing goes through `ingest.py::_num`.
- `contextMetrics.homeRunBallparks` is the exact park-adjusted would-be-HR
  count (0–30) — no separate park-dimensions dataset is needed.
- Events are keyed by `play_id` for deduplication.
- Only `pitch_call == "hit_into_play"` rows with a `launch_speed` are kept.
- **Weather comes from the MLB schedule API** (`hydrate=weather`), not Savant —
  the Savant gamefeed has no weather. `ingest_date` stamps venue/weather onto
  each game's events via `_attach_weather`. If the hydrated schedule returned an
  empty weather object for a final game, it falls back to that game's live feed
  (`fetch_live_weather`). Missing weather stays None/"" and is treated as
  neutral downstream.

**Sources:** `hr_tracker/store.py`, `hr_tracker/models.py`,
`hr_tracker/ingest.py`, `hr_tracker/site.py`
