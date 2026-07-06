# CLAUDE.md

Daily HR-Proximity Tracker: ingests every MLB game's batted-ball data from Baseball
Savant, classifies each event against three near-HR definitions, computes rolling
player trends, and publishes a static dashboard to `docs/` (GitHub Pages, live at
https://uncleblazerr.github.io/flyout-trends/). Spec: `C:\Users\andre\HR-Proximity-Tracker-PRD.md`.

## Commands

```powershell
# Run the full pipeline for today (ET) — ingest, score, store, rebuild docs/
python scripts/run_pipeline.py

# Specific date / useful flags
python scripts/run_pipeline.py --date 2026-07-04
python scripts/run_pipeline.py --dry-run          # print JSON, no writes (skill path)
python scripts/run_pipeline.py --include-unfinished
python scripts/run_pipeline.py --skip-site

# Backfill a historical range (data only, no site rebuild)
python scripts/backfill.py --days 2
python scripts/backfill.py --start 2026-07-01 --end 2026-07-04

# Unit tests
python -m pytest tests/ -q

# Page smoke test (jsdom lives in %TEMP%\hrtracker-pagetest, not the repo)
python -m http.server 8123 -d docs    # in background
node tests/page_smoke.mjs
```

Dependencies: Python stdlib + `requests` + `PyYAML` only (`requirements.txt`).
Frontend is vanilla HTML/CSS/JS embedded in `hr_tracker/site.py` — no build step,
no npm packages in the repo.

## Architecture

Pipeline stages, one module each, orchestrated by `scripts/run_pipeline.py`:

- `hr_tracker/models.py` — `BattedBallEvent` dataclass, `load_config`/`find_config`
- `hr_tracker/ingest.py` — MLB Stats API schedule + Savant `/gf?game_pk=` gamefeed
- `hr_tracker/scoring.py` — pure functions; the three near-HR definitions
- `hr_tracker/store.py` — `EventStore` Protocol + `FlatFileStore` (swappable backend)
- `hr_tracker/trends.py` — rolling 7/14/30-day windows, slope, `heating_up` flag
- `hr_tracker/prediction.py` — streaks, 0–100 expectancy score, empirical band
  rates, prediction receipts (`data/predictions/`) + their resolution
- `hr_tracker/site.py` — writes `docs/index.html` + `docs/data/{meta,latest,trends,predictions}.json`

All thresholds and weights live in `config.yaml` — never hardcode them.
`.claude/skills/hr-proximity/SKILL.md` and the GitHub Actions workflow
(`.github/workflows/hr-tracker.yml`, cron 06:00/23:00 ET) both call the same
`run_pipeline.py` path; keep it the single entry point.

## Data model and storage rules

- `data/raw/YYYY-MM-DD.json` is one full day, `schema_version: 1`. Re-running a
  date rewrites its file **in full** (never append), and `write_day` drops that
  date's entries from `data/rollups/player_index.json` before re-adding them.
- Only Final games (statusCode `F`/`O`) are ingested by default so in-progress
  games never pollute a day file.
- Near-HR flags **exclude actual home runs** (an HR is not "near" an HR).
- `data/predictions/YYYY-MM-DD.json` are append-only receipts of the players
  flagged that day; `resolve_prediction_records` measures the model's real hit
  rate from them, so never rewrite old ones (except by re-running that date).
- All prediction math reads the rollup via `store.read_player_days()` — don't
  re-scan raw event files for it. Rollup days written before the
  `near_hr_any` field existed are handled by the `_near_hr_any` fallback in
  `hr_tracker/prediction.py`.

## Savant feed gotchas

- Numeric fields (`launch_speed`, `hit_distance`, `launch_angle`) arrive as
  **strings**; `hc_x`/`hc_y` are floats. All parsing goes through
  `hr_tracker/ingest.py::_num` — keep it that way.
- `contextMetrics.homeRunBallparks` is the exact park-adjusted would-be-HR count
  (0–30). Do not add a park-dimensions dataset; the PRD's research spike is moot.
- Events are keyed by `play_id` for deduplication; only `pitch_call ==
  "hit_into_play"` rows with a launch_speed are kept.

## Git

- Commits must use `UncleBlazerr <216647226+UncleBlazerr@users.noreply.github.com>`
  (already set in local git config). Never commit with the personal email —
  history was scrubbed once to remove it.
- The repo is public. `data/` and `docs/` are committed on purpose (the Actions
  workflow commits them back after each scheduled run).
