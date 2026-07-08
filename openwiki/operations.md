# Operations

How the pipeline runs in production and locally, plus testing, deployment, and
git conventions.

## GitHub Actions workflow

**File:** `.github/workflows/hr-tracker.yml`

The workflow runs on a cron schedule three times daily:

| Cron (UTC) | ET | Purpose |
|---|---|---|
| `0 10 * * *` | 06:00 ET | Morning sweep — re-processes **yesterday** ET (the completed slate) |
| `0 16 * * *` | 12:00 ET | Noon sweep — re-processes **yesterday** ET after MLB posts game-day forecasts, so the published ranking carries real weather factors |
| `0 3 * * *` | 23:00 ET | Evening sweep — processes **today** ET (catches day games + early finals) |

All three also run via `workflow_dispatch`, accepting an optional `date` input.

### Morning run (`--yesterday`)

The 06:00 ET run processes **yesterday** in US Eastern time. This is important:
if the 23:00 ET run slips past midnight, GitHub cron would fire the new
(likely empty) day instead. The morning run self-heals by always anchoring to
the completed slate.

### Noon run (`--yesterday`)

The 12:00 ET run also re-processes **yesterday** ET. MLB posts game-day
forecasts mid-morning, so the 06:00 ET run ranks mostly neutral (forecasts
not yet available). The noon run picks up those forecasts, so the published
ranking carries real weather factors before first pitch.

### Evening run (today ET)

The 23:00 ET run processes today ET — the day's games that have gone final by
then.

### Workflow steps

1. Checkout repo, set up Python 3.12, install dependencies.
2. Run `python scripts/run_pipeline.py` (with `--yesterday` for the morning
   and noon runs, or `--date` for manual dispatch).
3. Commit `data/` and `docs/` back to `main` as `hr-tracker-bot` if there are
   changes.
4. Push.

`permissions: contents: write` — needed to push commits. The workflow uses
`concurrency: { group: hr-tracker, cancel-in-progress: false }` so runs never
overlap.

## Local development

```bash
# Today (ET), full pipeline
python scripts/run_pipeline.py

# Yesterday ET (the completed slate — right anchor for morning/noon runs)
python scripts/run_pipeline.py --yesterday

# Specific date
python scripts/run_pipeline.py --date 2026-07-04

# Dry run — no writes, prints JSON to stdout
python scripts/run_pipeline.py --dry-run

# Skip site rebuild (data only)
python scripts/run_pipeline.py --skip-site

# Include in-progress games
python scripts/run_pipeline.py --include-unfinished

# Use a custom config file
python scripts/run_pipeline.py --config path/to/config.yaml

# Backfill a historical range (oldest first, data only, no site rebuild)
python scripts/backfill.py --days 2
python scripts/backfill.py --start 2026-07-01 --end 2026-07-04
python scripts/backfill.py --sleep 2.0    # be polite between dates (default 1.0s)
```

### Viewing the dashboard locally

```bash
python -m http.server -d docs 8000   # → http://localhost:8000
```

## GitHub Pages deployment

The repo publishes `docs/` as a static site via GitHub Pages (source: "Deploy
from a branch", branch `main`, folder `/docs`). Live at
https://uncleblazerr.github.io/flyout-trends/.

**After every push**, verify the Pages build and deployment succeeds:
```bash
gh run list
gh api repos/UncleBlazerr/flyout-trends/pages/builds/latest
```
If it fails (transient "Deployment failed, try again later" errors are
common), re-trigger with:
```bash
gh api -X POST repos/UncleBlazerr/flyout-trends/pages/builds
```
Cap fix attempts at 10, then stop and report to the user.

## Testing

### Python unit tests

```bash
python -m pytest tests/ -q
```

| File | Coverage |
|---|---|
| `tests/test_scoring.py` | All three near-HR flags, boundary thresholds, HR exclusion, barrel score bounds and monotonicity |
| `tests/test_ingest.py` | Gamefeed parsing, string-to-float conversion, deduplication, missing-field handling, roundtrip serialization |
| `tests/test_store_trends.py` | Store write/read roundtrip, immutability across dates, rollup replacement, `linear_slope`, `compute_trends` with `heating_up` |
| `tests/test_prediction.py` | Streak computation (gaps, staleness, non-qualifying days), expectancy scoring, empirical rates, prediction records, cross-check, consistency leaderboard |
| `tests/test_weather.py` | Weather correlation table, temperature band labels, bucketing, rate hiding behind min_samples |
| `tests/test_site.py` | `build_site` writes player pages, player pages span the trend window, form data correctness |

`tests/conftest.py` provides a session-scoped `config` fixture that loads
`config.yaml` from the repo root.

### Page smoke test (JavaScript)

```bash
# In one terminal:
python -m http.server 8123 -d docs
# In another:
node tests/page_smoke.mjs
```

Loads the built dashboard in jsdom and asserts that tables render rows with
real data, the "Most Likely to Homer" section is visible and sorted by
expectancy descending, the meta line contains a date, and the consistency
leaderboard is ranked correctly. jsdom is installed to a temp directory, not
the repo — no npm packages in the repo.

## Git conventions

- Commits must use `UncleBlazerr <216647226+UncleBlazerr@users.noreply.github.com>`
  (already set in local git config). Never commit with the personal email —
  history was scrubbed once to remove it.
- The Actions workflow commits as `hr-tracker-bot <actions@github.com>`.
- The repo is public. `data/` and `docs/` are committed on purpose (the
  Actions workflow commits them back after each scheduled run).
- If `git push` is rejected, `git pull --rebase` and push again.

## Dependencies

Python 3.12, stdlib + `requests` + `PyYAML` only (`requirements.txt`). The
frontend is vanilla HTML/CSS/JS embedded in `hr_tracker/site.py` — no build
step, no npm packages in the repo.

## Agent skills and integrations

See [Integrations](integrations.md) for the Claude Code skill, savant-analyst
subagent, and Hermes-agent integration.

**Sources:** `.github/workflows/hr-tracker.yml`, `scripts/run_pipeline.py`,
`scripts/backfill.py`, `CLAUDE.md`, `tests/`
