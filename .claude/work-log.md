# Work Log

## 2026-07-06 — Weather Correlation PRD generated

**What was done:** Wrote `C:\Users\andre\HR-Weather-Correlation-PRD.md` (next to
the original tracker PRD, outside the public repo) and seeded `.claude/tasks.md`
with the 7-phase breakdown. No repo code changed.

**Data-source validation (live, 2026-07-05/06 games):**
- `statsapi.mlb.com/api/v1/schedule?sportId=1&date=...&hydrate=weather` returns
  per-game `{"condition","temp","wind"}` for the whole slate in one call.
  RotoGrinders scraping and Open-Meteo are unnecessary (Open-Meteo documented as
  future fallback only).
- Wind direction is already park-relative (`Out To CF`, `In From LF`, `L To R`,
  `Calm`, `Varies`) — no park-orientation geometry needed for the wind-out rule.
- Domes explicit (`condition: "Dome"`, Tropicana verified). Pre-game weather is
  populated hours before first pitch (Nationals Park Preview game verified);
  far-off games can return `weather: {}` → neutral.
- Savant `/gf` has no weather (verified) — this is a schedule-level fetch.
- `temp` is a string, same numbers-as-strings gotcha as Savant.

**Key design decisions (locked in PRD §7):**
- Weather factor = post-blend multiplier on the expectancy score (weights still
  sum to 1); all knobs in a new `prediction.weather:` config block.
- Empirical score bands + receipt resolution stay keyed to the **base** score in
  v1; receipts record `weather_factor` + inputs so a later phase can re-key
  empirically. This avoids drifting the self-calibration.
- Boost only for out-blowing wind ≥ threshold; in-wind = mild penalty;
  cross/calm/varies/dome/missing = neutral (factor 1.0).
- `SCHEMA_VERSION` 1 → 2; weather denormalized onto events + per-day rollup.
- Historical backfill via `backfill.py` (data-only, receipts untouched).

**Blockers:** none. Implementation not started — awaiting user approval of the
task list per CLAUDE.md protocol.

## 2026-07-06 — Phase 1 (weather ingest) complete

**Commit:** 937b8d6 on `feature/weather-ingest` (not pushed).

**What was done:**
- `hr_tracker/ingest.py`: `fetch_schedule` now sends `hydrate=weather` and
  returns venue + parsed weather per game; new `parse_wind` (park-relative
  phrase -> out/in/cross/none/varies, unrecognized -> varies + log warning);
  `fetch_live_weather` fallback (live feed with `fields=` trim) used only when
  a final game's schedule weather object is empty; `_attach_weather` stamps
  fields onto each game's events inside `ingest_date`.
- `hr_tracker/models.py`: `BattedBallEvent` gains optional `venue_id`,
  `venue_name`, `temp_f`, `wind_mph`, `wind_dir`, `weather_condition`
  (defaults keep old JSON loading; round-trip preserved). SCHEMA_VERSION
  still 1 — bump is Phase 2 with the rollup change.
- `tests/test_ingest.py`: parse_wind vocabulary table, hydrated-schedule
  sample (populated/dome/empty), FakeSession-driven `ingest_date` stamping +
  live-feed fallback tests. 62 tests pass.

**Verification (real API, dry-run so no writes):** 2026-07-05 slate = 15/15
games weather-tagged (Truist 89°F/5mph out matches direct API check; Roof
Closed parks -> wind none); 2026-07-01 (older date, backfill path) also fully
tagged; offseason 2026-01-15 (0 games) clean. Live-feed fallback exercised in
unit tests only — no real game had empty schedule weather.

**Decisions:** stamping happens per-game inside `ingest_date` so
`parse_events` stays Savant-only; weather keys centralized in
`_WEATHER_KEYS`; `ingest_date` signature unchanged (both scripts unaffected).

**Next:** Phase 2 — rollup weather fields + SCHEMA_VERSION 2 (same branch).

## 2026-07-06 — Phase 2 (rollup weather + schema v2) complete

**Commit:** bf25451 on `feature/weather-ingest` (not pushed).

**What was done:**
- `hr_tracker/store.py::_update_rollup`: each player-day now carries
  `temp_f`/`wind_mph`/`wind_dir`; fields fill from the first weather-tagged
  event of the day (doubleheaders keep game one). Pre-v2 rollup days simply
  lack the keys — downstream must read with `.get()` (Phase 4).
- `hr_tracker/models.py`: SCHEMA_VERSION 1 -> 2; `config.yaml` schema_version
  mirrored to 2 (no code reads it; declarative only).
- Tests: `make_event` builder carries weather defaults so store/trends/site
  tests exercise the new fields; schema assertion -> 2; two new rollup weather
  tests (carry + first-tagged-fill). 64 pass. `test_prediction.py::day`
  builder untouched — updating it belongs to Phase 4 when prediction reads
  weather.

**Verification (real pipeline, scratch storage via --config so repo data/
untouched):** full run for 2026-07-05 wrote raw v2 with all 771 events
weather-tagged, rollup with 286/286 player-days carrying weather
(out=93/in=19/cross=114/none=60, temps 70-94°F); site build succeeded with
the new payload keys; re-running the same date was idempotent (no dupes, no
key loss).

**Note for Phase 3:** repo `data/rollups/player_index.json` still holds v1
days without weather keys; the backfill re-ingest will rewrite them all.

**Next:** Phase 3 — historical weather backfill (`feature/weather-backfill`).

## 2026-07-06 — Phase 3 (historical weather backfill) complete

**Commit:** 290a647 on `feature/weather-backfill` (branched off
feature/weather-ingest; not pushed).

**What was done:** `py scripts/backfill.py --start 2026-07-04 --end 2026-07-06`
re-ingested all three stored dates with the Phase 1/2 weather code. All raw
files now schema v2 with 0 events missing weather; rollup 590/590 player-days
weather-tagged (out=188, cross=209, none=117, in=76). Integrity-diffed old vs
new day files: 07-04 (731 events) and 07-05 (771) have identical play_id sets
and identical scoring fields — only weather added. 07-06's previous file was
an empty stub from the morning run; it now holds the day's 1 final game
(62 events). data/predictions/ receipts untouched (verified via git status).

**⚠ Merge-timing risk:** RESOLVED — phases 1-3 merged to main (b8902f6) and
pushed 2026-07-06, ahead of the 23:00 ET cron, so tonight's run ingests with
weather code. Pages build for b8902f6 verified (`built`, no error) and the
live site returns 200; the push-triggered OpenWiki Update workflow succeeded
(auto-merged its docs PR, which advanced origin/main).

**Next:** Phase 4 — weather_factor + prediction integration
(`feature/weather-score`).

## 2026-07-06 — Phase 4 (weather-adjusted ranking) complete

**Commit:** 288eca3 on `feature/weather-score` (branched off post-merge main;
not pushed).

**What was done:**
- `hr_tracker/prediction.py`: pure `weather_factor(wx, config)` — temp linear
  around `temp_ref_f`, wind bonus ONLY for `out` >= `wind_out_min_mph`,
  gentler `in` penalty, cross/varies/calm neutral, `neutral_conditions`
  (Dome/Roof Closed) and empty forecasts exactly 1.0, total clamped to
  `clamp`. `compute_predictions` takes `team_weather`, ranks by
  `adjusted_score = expectancy_score * weather_factor`; entries gain
  `weather_factor`, `adjusted_score`, `game_weather`. Bands/cross_check/
  consistency stay keyed to base score (PRD §6.5).
- `hr_tracker/ingest.py`: schedule hydrate is now `weather,team`
  (abbreviations verified to match all 30 rollup Savant team codes);
  game dicts carry home_team/away_team; new `upcoming_team_weather(date,
  config)` maps team -> its game's weather with live-feed fallback,
  first-game-wins for doubleheaders.
- `scripts/run_pipeline.py`: builds the map for as_of+1 (the follow-up
  window's first slate), passes it to both compute_predictions calls; fetch
  failure degrades to neutral, never fails the pipeline.
- `config.yaml`: new `prediction.weather:` block (defaults per PRD §5.3).
- Tests: 13 new (factor math incl. clamp both ways + disabled + dome;
  ranking by adjusted score with identical forms; neutral without map/for
  idle teams; upcoming_team_weather mapping incl. fallback + doubleheader +
  all-empty). 77 pass.

**Verification (real API, scratch storage):** pipeline for 07-04 -> upcoming
07-05 mapped 30/30 teams with actuals, all 15 receipt entries adjusted
(Sutter Health 83F/9mph out = 1.166; Truist 89F/5 out = 1.141), ranked by
adjusted_score, base*factor==adjusted for all. Pipeline for 07-05 -> today's
8-game slate mapped 16/16; wind-in Busch = 0.987 penalty; idle teams (ATH)
neutral with game_weather null. Dry-run as-of today -> tomorrow 30 teams/0
forecasts, every factor exactly 1.0. Receipts embed the weather config block.

**Known behavior:** next-day forecasts are empty in both schedule and live
feed until game morning, so the 23:00 ET run is usually neutral and the
06:00 ET --yesterday run (upcoming = that same day) gets real weather. The
morning run is where the weather adjustment actually bites. Open-Meteo
fallback (PRD §8) would close this gap if it ever matters.

**Next:** Phase 5 — correlation aggregation + weather.json
(`feature/weather-correlation`). Note: `test_prediction.py::day` builder
still has no weather fields — Phase 5's correlation reads day weather, so
extend it there.

## 2026-07-06 — Phase 5 (weather correlation table) complete

**Commit:** 9ddaecb on `feature/weather-correlation` (branched off
feature/weather-score; not pushed).

**What was done:**
- New `hr_tracker/weather.py::weather_correlation(player_days, config,
  as_of)`: buckets every rollup player-day into temp-band x wind-class cells
  (out / in / neutral; cross+calm+varies collapse to neutral), dome/closed-
  roof days in their own row (keyed off the new rollup `weather_condition`
  vs `weather.neutral_conditions`), weatherless days counted as
  `unknown_player_days` but never bucketed. Measures per cell: player_days,
  hr_days/hr_total (+hr_rate), near_hr_days (+near_hr_rate), and
  near-HR->HR follow-through within horizon_days with the same censoring as
  `empirical_rates`. Rates null below `weather.min_samples` ("collecting
  data"). Reuses `band_label`, `_hr_within`, `_near_hr_any` from prediction.
- `store.py::_update_rollup`: player-days now also carry
  `weather_condition` (first tagged event wins; "" normalizes to None).
- `site.py::build_site`: new `weather_corr` param -> writes
  `docs/data/weather.json`. `run_pipeline.py` computes and passes it,
  logging a `[weather]` summary line.
- `config.yaml` weather block: `temp_bands: [55, 70, 85]`,
  `min_samples: 25`.
- Tests: new `tests/test_weather.py` (bucketing, dome separation, unknown
  days, follow-through + censoring, min_samples gating, empty rollup) with
  its own weather-day builder (test_prediction's `day()` intentionally left
  weatherless — prediction still never reads day weather). 84 pass.

**Verification (real API, fresh scratch storage):** backfill 07-04 +
pipeline 07-05 produced weather.json over 451 outdoor + 117 dome player-days
in 7 cells. Even 2 days of data point the right way: 85+/out HR-day rate
0.205, 70-85/out 0.143, 70-85/neutral 0.108, 70-85/in 0.051 — hot + wind out
leads, wind in kills. Gated cells (<25 days) show null rates; follow_rate
fully censored (needs horizon+1 days of history); dome row separated;
unknown=0.

**⚠ Data follow-up after merge:** the repo rollup predates the
weather_condition rollup key. After merging phases 4+5 to main, run
`py scripts/backfill.py --start 2026-07-04` ON MAIN and push, so dome days
classify correctly in the live weather.json. Deliberately NOT done on the
branch to avoid data-file merge conflicts with tonight's 23:00 ET cron.

**Next:** Phase 6 — dashboard weather columns + correlation panel
(`feature/weather-ui`).

## 2026-07-06 — Phase 6 (dashboard weather UI) complete; phases 4-6 merged

**Commits:** 9927ff2 (UI) on `feature/weather-ui`; merged to main with
phases 4-5; data/docs refresh 0a06656.

**UI changes (`hr_tracker/site.py`):**
- Most-likely table: new Adj column (weather-adjusted score; rows rank by
  it, tooltip carries the factor) and Next-game column (upcoming game's
  temp + park-relative wind via shared `wxText` JS helper: ↑out ↓in ↔cross;
  Dome/Roof Closed shown as-is). Section note explains the adjustment.
- Expectancy chart plots the adjusted score; tooltip gains a
  "Next: <weather> · weather ×f" line; title says "Weather-adjusted".
- Near-HR events table + player-page day table: Wx column.
- New "HR rate by weather" section rendering docs/data/weather.json:
  temp-band x wind rows + dome row, "collecting (n/min)" gating, self-
  explanatory note.
- `tests/page_smoke.mjs`: asserts adjusted-order ranking (td[4]), Next-game
  and events/player Wx cells, weather panel rows/note, new table order; port
  overridable via SMOKE_PORT (three stale http.servers were squatting 8123 —
  killed, but the env override future-proofs it).

**Verification:** jsdom smoke test PASSED against a scratch-built site
(adjusted top score 72.6 rendered, weather panel 8 rows, player day Wx).

**Merge + data (main):** merged phases 4-6 (84 tests pass), ran
`backfill.py --start 2026-07-04 --end 2026-07-06` so rollup days carry
weather_condition, then the full pipeline for 07-06 (5/8 games final at run
time; the 23:00 ET cron and tomorrow's --yesterday run pick up the rest).
Correlation now spans 531 outdoor + 133 dome player-days. Pushed as 0a06656.

**Remaining:** Phase 7 docs (README/CLAUDE.md/openwiki) — not started.
