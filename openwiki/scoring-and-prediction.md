---
type: Domain Model
title: Scoring & Prediction
description: Near-HR scoring definitions, expectancy model, weather adjustment, empirical follow-up rates, and self-checking receipts for the Daily HR-Proximity Tracker.
tags: [scoring, prediction, near-hr, expectancy, weather, receipts]
---

# Scoring & Prediction

How batted-ball events are classified as "near-HR" and how players are ranked
by HR expectancy. All thresholds and weights live in `config.yaml`.

## Three near-HR definitions

Every non-HR batted ball is classified against three independent definitions.
A single event can trigger none, one, two, or all three. Actual home runs are
excluded from all near-HR flags (an HR is not "near" an HR).

### 1. Distance threshold (`distance_flag`)

A non-HR result in the configured result list (Flyout, Lineout, Double, Single,
Sac Fly) with `hit_distance` exceeding `near_hr.distance.threshold_ft`
(default 350 ft).

Config: `near_hr.distance.results`, `near_hr.distance.threshold_ft`

### 2. Park-adjusted would-be-HR (`would_be_hr_flag`)

Uses Savant's `contextMetrics.homeRunBallparks` — the exact count of the 30 MLB
parks where the ball would have been a home run. A non-HR event is flagged when
`would_be_hr_count` ≥ `near_hr.would_be_hr.min_parks` (default 5).

This is not an approximation: Savant publishes the exact number in the
gamefeed. The PRD's park-dimensions research spike is moot.

Config: `near_hr.would_be_hr.min_parks`

### 3. Composite barrel-proximity score (`barrel_score` / `barrel_flag`)

A 0–100 weighted blend of three components:

| Component | How it's computed | Config |
|---|---|---|
| Exit velocity | Linear interpolation from `exit_velocity_range` (70–115 mph → 0–1) | `weights.exit_velocity: 0.4` |
| Launch angle | Full credit at `ideal_launch_angle` (27.5°), zero at ± `launch_angle_tolerance` (27.5°) | `weights.launch_angle: 0.3` |
| Distance | Linear interpolation from `distance_range` (0–450 ft → 0–1) | `weights.distance: 0.3` |

`barrel_flag` fires when a non-HR event's `barrel_score` ≥
`near_hr.barrel_score.min_score` (default 70).

Config: `near_hr.barrel_score` section.

### `is_near_hr` property

An event is "near-HR" if any of the three flags fire:
`distance_flag or would_be_hr_flag or barrel_flag`.

**Source:** `hr_tracker/scoring.py` — all pure functions, no I/O.

## HR expectancy model

`hr_tracker/prediction.py` ranks active hitters by a 0–100 expectancy score.
The model reads only the per-player per-day rollup (`store.read_player_days()`);
raw event files are never re-scanned for prediction math.

### Three signals

1. **Streak** — Consecutive qualifying appearance days (days with ≥
   `min_near_hr_events` near-HR events) ending at the player's most recent
   appearance. Rest-day gaps ≤ `max_gap_days` (default 2) don't break it. A
   non-qualifying day or a stale last appearance does. Capped at `streak_cap`
   (default 5) for scoring.

2. **Frequency** — Of the player's last `slope_window` (default 7) appearance
   days, what fraction were qualifying.

3. **Intensity** — Average of three normalized slopes over the last
   `slope_window` appearance days, each capped at 1.0:
   - `max_ev` slope (mph/day, full credit at `intensity_scales.max_ev`: 2.0)
   - `parks_sum` slope (would-be-HR parks/day, full credit at 3.0)
   - `near_hr` slope (near-HR events/day, full credit at 1.0), with
     extra-base near-HR events weighted by `xbh_weight` (1.25) vs 1.0 for outs

### Expectancy score

```
score = 100 * (w_streak * min(streak, cap) / cap
             + w_frequency * frequency
             + w_intensity * intensity)
```

Default weights: `streak: 0.4`, `frequency: 0.3`, `intensity: 0.3` (must sum
to 1.0).

### XBH weighting

Near-HR events that went for doubles or triples weigh `xbh_weight` (1.25)
instead of 1.0 — a ball that already went for extra bases is better evidence
than one caught at the track. This applies to the `near_hr` intensity series
only.

### Per-player entry

Each ranked player carries:
- `expectancy_score`, `streak`, `frequency`, `slopes` (max_ev / parks_sum /
  near_hr)
- `weather_factor`, `adjusted_score` (= `expectancy_score × weather_factor`)
- `game_weather` (venue/temp/wind from the player's upcoming game, or null)
- `near_hr_7d`, `near_hr_xbh_7d`, `hr_7d`, `max_ev_7d`, `max_distance_7d`
  (informational — HR count doesn't move the score)
- `band` label and `band_rate` (empirical follow-up rate, or null)
- `band_samples` (number of historical samples in the player's band)
- `repeat` (also flagged on the previous pull)

Players are sorted by `adjusted_score`, then by `near_hr_7d`. The list is
truncated to `prediction.top_n` (default 15).

## Weather adjustment

`weather_factor()` applies a multiplier to the ranking score based on the
player's upcoming-game forecast (fetched by `ingest.upcoming_team_weather()`
for the day after `as_of`). The multiplier combines a temperature term and a
wind term:

- **Temperature**: `1 + temp_per_deg × (temp_f − temp_ref_f)` — hotter boosts,
  colder penalizes.
- **Wind out**: bonus when wind_dir is `out` and wind_mph ≥ `wind_out_min_mph`,
  scaled by `wind_out_per_mph` up to `wind_out_cap_mph`.
- **Wind in**: gentler penalty when wind_dir is `in` and wind_mph ≥
  `wind_in_min_mph`, scaled by `wind_in_per_mph` up to `wind_in_cap_mph`.
- **Neutral**: cross/calm/varies winds, domes/roof-closed
  (`neutral_conditions`), disabled config, and missing weather all yield
  exactly 1.0.
- The total factor is clamped to `[clamp[0], clamp[1]]` (default 0.85–1.20).

Bands and the empirical self-check stay keyed to the base `expectancy_score`
so historical calibration is not distorted by a factor old rollup days never
had.

Config: `prediction.weather` section.

## Empirical band rates

`empirical_rates()` measures the model's own accuracy from stored history:
of all past player-days scoring in the same band, how often did an HR follow
within `prediction.horizon_days` (default 3)?

- Days too close to the newest stored date to have full follow-up are
  **censored** (excluded).
- The rate is hidden below `prediction.min_samples` (default 20) — the model
  doesn't claim a rate until it has enough data.
- Score bands: `<40`, `40-60`, `60-80`, `80+` (configurable via
  `prediction.score_bands`).

This self-calibrates as stored history grows.

## Prediction receipts and self-checking

### Append-only receipts

Each full pipeline run writes `data/predictions/YYYY-MM-DD.json` — a receipt
of what was flagged that day (player list, scores, config snapshot). These are
append-only; never edit past dates. Re-running a date supersedes that date's
record (mirroring `write_day` semantics).

### `annotate_repeats`

Marks players who also appeared on the most recent prior record. Making the
list again means another qualifying performance since being flagged — shown as a
↻ badge on the dashboard.

### `cross_check`

Finds flagged players from recent records (within `horizon_days` of the current
date) who have since homered. Shown as 💥 chips on the dashboard. Older
conversions roll up into the aggregate track record.

### `resolve_prediction_records`

Measures the model's overall hit rate: of all resolved prediction records
(those old enough for a full `horizon_days` follow-up), how many flagged
players actually homered. Reports both overall and top-band rates. Returns None
until at least one record resolves.

### `consistency_leaderboard`

Surfaces players who keep re-qualifying for the Most-Likely list across
consecutive pulls. Ranked by the player's current run of consecutive
prediction records they appear on (ending at the most recent record), then by
lifetime flag count and average score. Only players on the most recent record
are included — this is a "who's hot right now" view. Truncated to
`prediction.consistency_top_n` (defaults to `top_n` if unset).

## Key config reference

| Config path | Default | Purpose |
|---|---|---|
| `near_hr.distance.threshold_ft` | 350 | Distance flag threshold |
| `near_hr.would_be_hr.min_parks` | 5 | Would-be-HR flag threshold (0–30) |
| `near_hr.barrel_score.min_score` | 70 | Barrel flag threshold (0–100) |
| `near_hr.barrel_score.weights` | 0.4/0.3/0.3 | EV/LA/distance blend |
| `prediction.weights` | 0.4/0.3/0.3 | Streak/frequency/intensity blend |
| `prediction.max_gap_days` | 2 | Rest-day gap that keeps a streak alive |
| `prediction.slope_window` | 7 | Appearance days for intensity slopes |
| `prediction.streak_cap` | 5 | Streak component max |
| `prediction.xbh_weight` | 1.25 | Doubles/triples weight in intensity |
| `prediction.horizon_days` | 3 | Follow-up window for empirical rates |
| `prediction.score_bands` | [40, 60, 80] | Band edges for empirical rates |
| `prediction.min_samples` | 20 | Minimum samples to show a band rate |
| `prediction.top_n` | 15 | Size of "Most Likely to Homer" list |
| `prediction.consistency_top_n` | 15 | Size of consistency leaderboard (defaults to `top_n`) |
| `prediction.records_dir` | `data/predictions` | Where prediction receipts are written |
| `prediction.weather.enabled` | true | Toggle weather factor on/off |
| `prediction.weather.temp_ref_f` | 70 | Neutral temperature (°F) |
| `prediction.weather.temp_per_deg` | 0.004 | Multiplier per °F from ref |
| `prediction.weather.wind_out_min_mph` | 5 | Min mph for out-wind bonus |
| `prediction.weather.wind_out_per_mph` | 0.012 | Bonus per mph (out) |
| `prediction.weather.wind_out_cap_mph` | 20 | Max mph earning out-wind bonus |
| `prediction.weather.wind_in_min_mph` | 5 | Min mph for in-wind penalty |
| `prediction.weather.wind_in_per_mph` | 0.008 | Penalty per mph (in) |
| `prediction.weather.wind_in_cap_mph` | 20 | Max mph earning in-wind penalty |
| `prediction.weather.clamp` | [0.85, 1.20] | Bounds on total weather factor |
| `prediction.weather.neutral_conditions` | [Dome, Roof Closed] | Conditions with factor exactly 1.0 |
| `prediction.weather.temp_bands` | [55, 70, 85] | Correlation-view temperature bands |
| `prediction.weather.min_samples` | 25 | Min samples to show a correlation cell's rates |

**Sources:** `hr_tracker/scoring.py`, `hr_tracker/prediction.py`,
`hr_tracker/weather.py`, `config.yaml`, `tests/test_prediction.py`,
`tests/test_scoring.py`, `tests/test_weather.py`
