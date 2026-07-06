# Tasks

## Weather Correlation (PRD: C:\Users\andre\HR-Weather-Correlation-PRD.md)

- [x] Phase 1 — Ingest: add `hydrate=weather` to `fetch_schedule`, extract per-game venue + weather, wind-string parser (`out/in/cross/none/varies`), stamp weather fields onto `BattedBallEvent`, `feed/live` fallback for empty weather on final games; tests (parser vocabulary table, hydrated-schedule sample payloads: populated/empty/dome/varies)
  - Branch: feature/weather-ingest
  - Commit: 937b8d6 — verified end-to-end via `--dry-run` on 2026-07-05 (15/15 games weather-tagged) and 2026-07-01 (backfill path), offseason empty date clean
- [ ] Phase 2 — Store/rollup: bump `SCHEMA_VERSION` to 2, per-player-day `temp_f`/`wind_mph`/`wind_dir` in `_update_rollup`, update `make_event`/`day` builders + `schema_version` assertion, round-trip test with new fields
  - Branch: feature/weather-ingest
- [ ] Phase 3 — Backfill: one-time historical weather re-ingest of all dates in `data/raw/` via `scripts/backfill.py` (data-only; prediction receipts untouched)
  - Branch: feature/weather-backfill
- [ ] Phase 4 — Prediction: pure `weather_factor()` per PRD §5.2, `prediction.weather:` config block, team→upcoming-game weather map in `compute_predictions`, rank by `base_score × weather_factor`, keep empirical bands on base score, weather inputs in prediction entries + receipts; unit tests (hot+out compounding, out-below-threshold, in-penalty, cross-neutral, dome=1.0, clamp)
  - Branch: feature/weather-score
- [ ] Phase 5 — Correlation: aggregate rollup into temp-band × wind-class cells (HR rate, near-HR rate, near-HR→HR follow-through, sample counts; `min_samples` gating), emit `docs/data/weather.json`
  - Branch: feature/weather-correlation
- [ ] Phase 6 — Dashboard: weather column in "Most likely to homer" + near-HR events tables, correlation panel from `weather.json`, player-page day rows; extend `tests/page_smoke.mjs`
  - Branch: feature/weather-ui
- [ ] Phase 7 — Docs: README, CLAUDE.md (weather source + gotchas), openwiki pages, config comments (rolled into each phase's PR)
