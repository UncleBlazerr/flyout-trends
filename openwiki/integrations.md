# Integrations

Agent skills, subagents, and LLM integrations that layer on top of the
pipeline. All of them call the same `scripts/run_pipeline.py` entry point — no
duplicated logic.

## Claude Code Skill: `hr-proximity`

**File:** `.claude/skills/hr-proximity/SKILL.md`

A Claude Code Skill for ad hoc queries and runs. Key behaviors:

- **Default mode is `--dry-run`** (no writes): prints scored events +
  predictions as JSON to stdout. Used for answering questions like "who's most
  likely to homer?" without persisting anything.
- Documents how to read the published JSON in `docs/data/` —
  `predictions.json`, `latest.json`, `trends.json`, and per-player files — so
  most questions can be answered without a pipeline run at all.
- Documents the full pipeline path for when persistence is needed.
- Shows how to compute predictions programmatically:
  ```python
  from hr_tracker.prediction import compute_predictions
  preds = compute_predictions(store, "2026-07-05", config)
  ```

## Savant analyst subagent

**File:** `.claude/agents/savant-analyst.md`

A Claude Code subagent for Baseball Savant data analysis. Read-and-report by
default — runs the pipeline in dry-run mode and reads stored data, but does
not modify code or commit.

Key capabilities:
- Uses the `hr-proximity` skill as its primary tool.
- Can fetch raw Savant/MLB feeds directly for questions beyond pipeline output
  (pitch-level detail, specific plays, cross-checking numbers).
- Schedule API: `https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=YYYY-MM-DD`
- Gamefeed: `https://baseballsavant.mlb.com/gf?game_pk=<pk>`
- Prefers reusing `hr_tracker` modules over ad-hoc scripts so numbers always
  match the dashboard.
- Reports cite which definition of "near-HR" was used (distance, would-be-HR
  parks, or barrel score) and quote thresholds from `config.yaml`.

## Hermes-agent integration

**Files:** `hermes/README.md`, `hermes/skills/hr-proximity/SKILL.md`

[hermes-agent](https://github.com/nousresearch/hermes-agent) acts as a local
LLM companion to the GitHub Actions cron: a chat interface to the tracker, a
daily analysis writer, and a digest sender. Actions remains the reliable data
backstop — Hermes adds the LLM layer on top.

### Hermes skill

`hermes/skills/hr-proximity/SKILL.md` is the Hermes skill (agentskills.io
format). It covers:

- **Answering questions** — prefer the published JSON in `docs/data/` (no
  pipeline run needed). For dates not yet stored, use `--dry-run`.
- **Daily run** — a 5-step workflow: `git pull`, run pipeline for yesterday
  ET, write `docs/data/analysis.json`, commit and push, send the digest.
- **Rules** — never edit past prediction receipts, never change
  `config.yaml` thresholds unless asked, rebase on push rejection.

### `docs/data/analysis.json`

Written by the Hermes daily run, rendered as the "Today's read" section on
the dashboard. Shape:
```json
{
  "as_of": "2026-07-05",
  "generated_at": "2026-07-06T19:10:00Z",
  "model": "claude-sonnet-5",
  "text": "2-4 paragraphs of scouting-style analysis..."
}
```

The dashboard shows it only while `as_of` matches the latest data date, so a
stale blurb silently disappears. The `text` field contains plain sentences (no
markdown), with concrete numbers (EV, distances, streaks), 💥 conversions
where the model's flagged player homered, and notable near-misses.

### Hermes setup (once)

1. Install hermes-agent (Windows): `iex (irm https://hermes-agent.nousresearch.com/install.ps1)`
2. Set `OPENROUTER_API_KEY` in `%LOCALAPPDATA%\hermes\.env`; configure model
   provider in `%LOCALAPPDATA%\hermes\config.yaml`.
3. Copy the skill to
   `%LOCALAPPDATA%\hermes\skills\sports\hr-proximity\SKILL.md`.
4. Register the daily job (07:30 local, after the morning Actions sweep):
   ```
   hermes cron create "30 7 * * *" "Do the daily run exactly as the hr-proximity skill describes: git pull, run the pipeline, write docs/data/analysis.json, commit and push, then produce the digest." --name hr-daily --skill hr-proximity --workdir C:\Users\andre\flyout-trends --deliver local
   ```
5. Optional messaging digest: run `hermes gateway` setup for
   Telegram/Discord and change `--deliver local` to your platform.

### Ad hoc use

```
hermes -z "who is most likely to homer today and why?" --skill hr-proximity
```

**Sources:** `.claude/skills/hr-proximity/SKILL.md`,
`.claude/agents/savant-analyst.md`, `hermes/README.md`,
`hermes/skills/hr-proximity/SKILL.md`, `docs/data/analysis.json`
