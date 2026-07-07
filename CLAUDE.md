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

# Page smoke test (jsdom lives in %TEMP%\hrtracker-pagetest, not the repo).
# Stale servers tend to accumulate on 8123 — set SMOKE_PORT to sidestep them.
python -m http.server 8123 -d docs    # in background
node tests/page_smoke.mjs
```

Dependencies: Python stdlib + `requests` + `PyYAML` only (`requirements.txt`).
Frontend is vanilla HTML/CSS/JS embedded in `hr_tracker/site.py` — no build step,
no npm packages in the repo.

## Architecture

Pipeline stages, one module each, orchestrated by `scripts/run_pipeline.py`:

- `hr_tracker/models.py` — `BattedBallEvent` dataclass, `load_config`/`find_config`
- `hr_tracker/ingest.py` — MLB Stats API schedule (weather-hydrated) + Savant
  `/gf?game_pk=` gamefeed; `parse_wind`, `upcoming_team_weather`
- `hr_tracker/scoring.py` — pure functions; the three near-HR definitions
- `hr_tracker/store.py` — `EventStore` Protocol + `FlatFileStore` (swappable backend)
- `hr_tracker/trends.py` — rolling 7/14/30-day windows, slope, `heating_up` flag
- `hr_tracker/prediction.py` — streaks, 0–100 expectancy score, `weather_factor`
  (ranking multiplier), empirical band rates, prediction receipts
  (`data/predictions/`) + their resolution
- `hr_tracker/weather.py` — league-wide HR-vs-weather correlation cells
- `hr_tracker/site.py` — writes `docs/index.html` +
  `docs/data/{meta,latest,trends,predictions,consistency,weather}.json`

All thresholds and weights live in `config.yaml` — never hardcode them.
`.claude/skills/hr-proximity/SKILL.md` and the GitHub Actions workflow
(`.github/workflows/hr-tracker.yml`, cron 06:00/23:00 ET) both call the same
`run_pipeline.py` path; keep it the single entry point.

## Data model and storage rules

- `data/raw/YYYY-MM-DD.json` is one full day, `schema_version: 2` (v2 added
  venue/weather fields on events and per-day weather in the rollup). Re-running a
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

## Weather gotchas

- Weather comes from the MLB Stats API itself: `schedule?...&hydrate=weather,team`
  (one call for the whole slate) with a `fields`-trimmed
  `game/{pk}/feed/live` fallback per game. **No RotoGrinders scraping, no
  Open-Meteo, no API key** — don't add them (Open-Meteo is the documented
  future fallback in the PRD, nothing more). Savant's `/gf` has no weather.
- `weather.temp` is a **string** ("89") — same numbers-as-strings gotcha as
  Savant; it goes through `_num`.
- Wind arrives **already park-relative** ("5 mph, Out To CF"). The observed
  vocabulary (`Out To LF/CF/RF`, `In From …`, `L To R`, `R To L`, `Calm`,
  `None`, `Varies`) is handled by `ingest.py::parse_wind`; anything
  unrecognized classifies as `varies` (neutral) — never guess direction, and
  never add park-orientation geometry.
- Missing/empty weather (games far from first pitch, off-days) means a
  **factor of exactly 1.0**. MLB publishes forecasts only on game day, so the
  23:00 ET run ranks mostly neutral and the 06:00 ET `--yesterday` run is
  where the weather adjustment actually bites. This is expected, not a bug.
- The ranking sorts by `adjusted_score = expectancy_score × weather_factor`,
  but empirical bands, cross-checks, and receipt resolution stay keyed to the
  **base** `expectancy_score`. Do not re-key them to adjusted scores unless
  `docs/data/weather.json` has accumulated the samples to justify it.
- Dome/closed-roof phrases live in `prediction.weather.neutral_conditions`
  (config, not code) — extend the list there if the feed uses new wording.

## OpenWiki

This repository has documentation located in the /openwiki directory.

Start here:
- [OpenWiki quickstart](openwiki/quickstart.md)

OpenWiki includes repository overview, architecture notes, workflows, domain concepts, operations, integrations, testing guidance, and source maps.

When working in this repository, read the OpenWiki quickstart first, then follow its links to the relevant architecture, workflow, domain, operation, and testing notes.

## Session Continuity Protocol

### At Session Start (Before Starting Work)

1. **Read task state:**
   - Check `.claude/tasks.md` in project root
   - Identify completed `[x]`, in-progress, and blocked tasks
   - Use this as source of truth for current state

2. **Read execution history:**
   - Check `.claude/work-log.md` in project root
   - Review what was tried, decisions made, blockers hit
   - Do NOT re-derive this information

3. **Read OpenWiki context:**
   - Read `openwiki/quickstart.md`, then follow its links to the relevant
     architecture, workflow, domain, and operations notes for the task at hand
     (see the OpenWiki section below)

4. **Then proceed with the user's request**

**Do not ask the user to repeat information that exists in these records.**

## Task List Management

### When Given a PRD or Project Description

1. Break work into discrete, actionable tasks
2. Write to `.claude/tasks.md` in the project root (create if missing)
3. Present the task list and ask for approval before starting
4. Use this format:
   ```markdown
   - [ ] Task description
     - Branch: feature/branch-name
   ```

### As Work Progresses

1. Mark completed tasks with `[x]`
2. Add commit/PR links to completed tasks
3. Note blockers inline: `- [ ] Task 3 — BLOCKED: waiting on API access`
4. Keep the task list as source of truth for "what's left"

## Work Completion Protocol

### Before Marking Any Task Complete or Reporting Work as Done

1. **Update task list:**
   - Mark task with `[x]` in `.claude/tasks.md`
   - Add links to commits/PRs
2. **Write to work log:**
   - Append entry to `.claude/work-log.md` with timestamp
   - Document: what was done, decisions made, blockers encountered
   - Link to commits, PRs, or Jira tickets
3. **Verify the record stands alone:**
   - Could another agent (or future you) resume from this record?
   - Are decisions and context captured, not just results?
4. Then report completion to the user

Do not rely on conversation context to track state across turns.

## Git

- Commits must use `UncleBlazerr <216647226+UncleBlazerr@users.noreply.github.com>`
  (already set in local git config). Never commit with the personal email —
  history was scrubbed once to remove it.
- The repo is public. `data/` and `docs/` are committed on purpose (the Actions
  workflow commits them back after each scheduled run).
- **After every push, verify the Pages build and deployment succeeds** before
  calling the work done: check `gh run list` / `gh api
  repos/UncleBlazerr/flyout-trends/pages/builds/latest`, then confirm the live
  site serves the new content. If it fails, diagnose and retry (transient
  "Deployment failed, try again later" errors are common — re-trigger with
  `gh api -X POST .../pages/builds`). Cap fix attempts at 10, then stop and
  report to the user.
