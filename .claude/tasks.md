# Tasks

## Weather Correlation (PRD: C:\Users\andre\HR-Weather-Correlation-PRD.md)

- [x] Phase 1 — Ingest: add `hydrate=weather` to `fetch_schedule`, extract per-game venue + weather, wind-string parser (`out/in/cross/none/varies`), stamp weather fields onto `BattedBallEvent`, `feed/live` fallback for empty weather on final games; tests (parser vocabulary table, hydrated-schedule sample payloads: populated/empty/dome/varies)
  - Branch: feature/weather-ingest
  - Commit: 937b8d6 — verified end-to-end via `--dry-run` on 2026-07-05 (15/15 games weather-tagged) and 2026-07-01 (backfill path), offseason empty date clean
- [x] Phase 2 — Store/rollup: bump `SCHEMA_VERSION` to 2, per-player-day `temp_f`/`wind_mph`/`wind_dir` in `_update_rollup`, update `make_event`/`day` builders + `schema_version` assertion, round-trip test with new fields
  - Branch: feature/weather-ingest
  - Commit: bf25451 — verified with a full real pipeline run against scratch storage (771 events / 286 player-days all weather-tagged, schema 2, idempotent re-run); `day` builder update deferred to Phase 4 when prediction starts reading weather
- [x] Phase 3 — Backfill: one-time historical weather re-ingest of all dates in `data/raw/` via `scripts/backfill.py` (data-only; prediction receipts untouched)
  - Branch: feature/weather-backfill
  - Commit: 290a647 — 2026-07-04..06 re-ingested; 07-04/07-05 event sets + scoring byte-identical apart from weather; receipts untouched
  - Merged: phases 1-3 merged to main as b8902f6 and pushed 2026-07-06 (before the 23:00 ET cron); Pages build verified, live site 200
- [x] Phase 4 — Prediction: pure `weather_factor()` per PRD §5.2, `prediction.weather:` config block, team→upcoming-game weather map in `compute_predictions`, rank by `base_score × weather_factor`, keep empirical bands on base score, weather inputs in prediction entries + receipts; unit tests (hot+out compounding, out-below-threshold, in-penalty, cross-neutral, dome=1.0, clamp)
  - Branch: feature/weather-score
  - Commit: 288eca3 — verified with real pipeline runs (07-04: 15/15 entries weather-adjusted, hot+out=1.166 at Sutter Health; 07-05: wind-in penalty 0.987 at Busch, idle teams neutral; as-of today: 30 teams/0 forecasts → all factors exactly 1.0)
- [x] Phase 5 — Correlation: aggregate rollup into temp-band × wind-class cells (HR rate, near-HR rate, near-HR→HR follow-through, sample counts; `min_samples` gating), emit `docs/data/weather.json`
  - Branch: feature/weather-correlation
  - Commit: 9ddaecb — verified with real data (85+/out HR-day rate 0.205 vs 70-85/in 0.051; gating + dome row + censoring all correct). Rollup gains `weather_condition`; after merging, re-run `backfill.py --start 2026-07-04` on main so the live rollup picks the field up
- [x] Phase 6 — Dashboard: weather column in "Most likely to homer" + near-HR events tables, correlation panel from `weather.json`, player-page day rows; extend `tests/page_smoke.mjs`
  - Branch: feature/weather-ui
  - Commit: 9927ff2 — Adj + Next-game columns (ranking by Adj), events/player-day Wx columns, HR-rate-by-weather panel; jsdom smoke test extended and passing (SMOKE_PORT override added)
  - Merged: phases 4-6 merged to main as part of the 0a06656 push with rollup condition backfill + site rebuild
- [x] Phase 7 — Docs: README, CLAUDE.md (weather source + gotchas), openwiki pages, config comments (rolled into each phase's PR)
  - README Weather section + layout; CLAUDE.md "Weather gotchas" section, architecture/schema updates, SMOKE_PORT note. openwiki self-updated via its workflow (PRs #1–#3 auto-merged); config comments landed with phases 4–5

**All PRD phases complete** — weather ingestion, scoring, correlation, dashboard, backfill, and docs are live.
