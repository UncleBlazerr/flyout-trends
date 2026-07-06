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
