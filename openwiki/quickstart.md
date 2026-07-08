# Quickstart — Daily HR-Proximity Tracker

The **Daily HR-Proximity Tracker** (repo: `flyout-trends`) surfaces MLB hitters
who are squaring the ball up and trending toward a home run before it shows up
in box scores. Three times a day it ingests every game's Statcast batted-ball data
from Baseball Savant, classifies each event against three near-HR definitions,
persists an append-only dataset, computes rolling 7/14/30-day per-player trends,
ranks players by HR expectancy, and publishes a static dashboard via GitHub
Pages.

**Live dashboard:** https://uncleblazerr.github.io/flyout-trends/

## What it does

1. **Ingest** — Fetches the MLB schedule (with weather hydration) and Baseball
   Savant gamefeeds for a date, parses batted-ball events (only Final games by
   default). Venue and weather (temp, wind speed/direction) are stamped onto
   each event from the schedule API.
2. **Score** — Classifies every non-HR batted ball against three near-HR
   definitions: distance threshold, park-adjusted would-be-HR count, and a
   composite barrel-proximity score (0–100).
3. **Store** — Writes immutable per-date JSON files and maintains an incremental
   player-index rollup.
4. **Trends** — Computes rolling 7/14/30-day per-player stats with trend
   direction and a `heating_up` flag.
5. **Predict** — Ranks active hitters by a 0–100 expectancy score (streak +
   frequency + intensity), weather-adjusted via the upcoming game's
   forecast, backed by empirical follow-up rates and self-checking receipts.
6. **Weather correlation** — Buckets every rollup player-day into
   temperature × wind cells to produce a league-wide HR-vs-weather table.
7. **Publish** — Generates a static HTML/JSON dashboard in `docs/` for GitHub
   Pages.

## Quick start

```bash
pip install -r requirements.txt

# Full pipeline for today (US Eastern time)
python scripts/run_pipeline.py

# Process a specific date
python scripts/run_pipeline.py --date 2026-07-03

# Morning run: process yesterday's completed slate
python scripts/run_pipeline.py --yesterday

# Dry run — print scored events + predictions as JSON, no writes
python scripts/run_pipeline.py --dry-run

# Backfill a historical range (data only, no site rebuild)
python scripts/backfill.py --days 2
python scripts/backfill.py --start 2026-07-01 --end 2026-07-04

# View the dashboard locally
python -m http.server -d docs 8000   # → http://localhost:8000

# Run tests
python -m pytest tests/ -q
```

## Repository layout

```
hr_tracker/           importable package (workflow, skill, and agent share one code path)
  models.py           BattedBallEvent dataclass, config loading
  ingest.py           MLB schedule + Savant gamefeed fetch + parse
  scoring.py          the three near-HR metrics (pure functions)
  store.py            EventStore protocol + FlatFileStore (v1)
  trends.py           rolling 7/14/30-day per-player stats
  prediction.py       streaks, expectancy score, weather factor, empirical rates, receipts
  weather.py          league-wide HR-vs-weather correlation table
  site.py             static HTML/JSON dashboard generator
scripts/
  run_pipeline.py     CLI entrypoint (workflow, local, skill, agent)
  backfill.py         ingest a historical date range (oldest first)
config.yaml           all thresholds, weights, windows — never hardcode
data/raw/             one immutable JSON per date (schema_version inside)
data/rollups/         player_index.json incremental rollup
data/predictions/     daily receipts of flagged players (append-only)
docs/                 GitHub Pages source (generated, committed)
  index.html          main dashboard
  player.html         per-player page template
  data/               JSON payloads consumed by the frontend
.claude/skills/hr-proximity/SKILL.md   Claude Code Skill for ad hoc runs
.claude/agents/savant-analyst.md       Baseball Savant analyst subagent
.github/workflows/hr-tracker.yml       cron (06:00 + 12:00 + 23:00 ET) + dispatch
hermes/                                Hermes-agent integration (skill + daily analysis)
```

## Key principles

- **One entry point.** The GitHub Actions workflow, the Claude Code skill, the
  savant-analyst agent, and local runs all call `scripts/run_pipeline.py`.
  There is no duplicated logic.
- **Config-driven.** Every threshold and weight lives in `config.yaml`. Never
  hardcode scoring parameters.
- **Append-only receipts.** `data/predictions/YYYY-MM-DD.json` files are
  prediction receipts the model is graded on. Never edit past dates.
- **Only Final games ingested** by default, so in-progress games never pollute
  a day file.

## Dependencies

Python 3.12, stdlib + `requests` + `PyYAML` only. The frontend is vanilla
HTML/CSS/JS embedded in `hr_tracker/site.py` — no build step, no npm packages
in the repo.

## Where to go next

- [Architecture](architecture.md) — Pipeline stages, module responsibilities, design principles
- [Scoring & Prediction](scoring-and-prediction.md) — Near-HR definitions, expectancy model, self-checking
- [Data & Storage](data-and-storage.md) — File formats, schemas, EventStore protocol, migration path
- [Operations](operations.md) — CI/CD, backfill, testing, Pages deployment, git conventions, integrations

## Existing docs

- `README.md` — Project overview, near-HR definitions, usage examples
- `CLAUDE.md` — Agent instructions: commands, architecture, data rules, Savant gotchas, git conventions
- `.claude/skills/hr-proximity/SKILL.md` — Claude Code Skill for ad hoc runs
- `.claude/agents/savant-analyst.md` — Baseball Savant analyst subagent
- `hermes/README.md` — Hermes-agent integration (LLM analysis + digest)
