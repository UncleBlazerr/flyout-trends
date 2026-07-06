---
name: hr-proximity
description: "Query and operate the Daily HR-Proximity Tracker: near-HR events, who is most likely to homer, player trends, daily digest, and the dashboard's daily analysis blurb."
version: 1.0.0
author: flyout-trends
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [MLB, baseball, statcast, home-runs, predictions]
prerequisites:
  commands: [python, git]
---

# HR-Proximity Tracker

The repo at `C:\Users\andre\flyout-trends` tracks every MLB batted ball daily,
flags "near home runs" (three definitions), ranks hitters by HR expectancy,
and publishes https://uncleblazerr.github.io/flyout-trends/. All commands run
from that directory.

## Answering questions ("who's most likely to homer?", "how did X do?")

Prefer the published JSON — no pipeline run needed:

- `docs/data/predictions.json` — ranked "Most Likely to Homer" list. Per
  player: `expectancy_score` (0–100), `streak` (consecutive games with a
  near-HR), `slopes` (max_ev / parks_sum / near_hr; positive = intensifying),
  `hr_7d`, `max_ev_7d`, `max_distance_7d`, `band_rate` (empirical HR-follow
  rate, null while samples accumulate), `repeat` (also flagged previous pull).
  Top-level: `recent_hits` (flagged players who then homered) and `hit_rate`
  (the model's measured track record).
- `docs/data/latest.json` — the day's near-HR events with EV/LA/distance,
  Savant's park-adjusted HR-parks count, and barrel score.
- `docs/data/trends.json` — rolling 7/14/30-day per-player windows.
- `docs/data/players/<player_id>.json` — one player's full recent log.

For a date not yet stored: `python scripts/run_pipeline.py --dry-run --date
YYYY-MM-DD` prints scored events + predictions as JSON without writing.

## Daily run (data refresh + analysis + digest)

1. `git pull --rebase` (the GitHub Actions cron also commits data).
2. `python scripts/run_pipeline.py --yesterday` — ingests yesterday ET (the
   completed slate; running "today" mid-day would publish an empty board),
   writes data, rebuilds `docs/`.
3. Write `docs/data/analysis.json`: a 2–4 paragraph scouting-style read of
   the day based on `predictions.json` and `latest.json` — who's hot and why
   (name concrete numbers: EV, distances, streaks), any 💥 conversions where
   the model's flagged player homered, notable near-misses. JSON shape:
   `{"as_of": "<same as predictions.as_of>", "generated_at": "<UTC ISO>",
   "model": "<your model slug>", "text": "<paragraphs separated by blank
   lines>"}`. No markdown in `text`, plain sentences. The dashboard shows it
   only while `as_of` matches the latest data date.
4. `git add data/ docs/ && git commit -m "Daily run + analysis" && git push`
   (author identity is preset in the repo's git config — do not change it).
5. Send the digest (if a messaging platform is configured): top 5 by
   expectancy with one-line "why" each, any 💥 conversions, and the track
   record line. Keep it under ~15 lines.

## Rules

- Never edit files under `data/predictions/` for past dates — they are
  append-only receipts the model is graded on.
- Never change scoring thresholds/weights (`config.yaml`) unless the user
  explicitly asks.
- If `git push` is rejected, `git pull --rebase` and push again.
