# Hermes-agent integration

[hermes-agent](https://github.com/nousresearch/hermes-agent) acts as a local
companion to the GitHub Actions cron: a chat interface to the tracker, a daily
analysis writer, and a digest sender. Actions remains the reliable data
backstop — Hermes adds the LLM layer on top.

## Pieces

- `skills/hr-proximity/SKILL.md` — the Hermes skill (agentskills.io format).
  Canonical copy lives here; installed copy goes to
  `%LOCALAPPDATA%\hermes\skills\sports\hr-proximity\SKILL.md`.
- `docs/data/analysis.json` — written by the Hermes daily run, rendered as
  the "Today's read" section on the dashboard. Shape:
  `{as_of, generated_at, model, text}`. The page shows it only while `as_of`
  matches the latest data date, so a stale blurb silently disappears.

## Setup (once)

1. Install hermes-agent (Windows): `iex (irm https://hermes-agent.nousresearch.com/install.ps1)`
2. Put `OPENROUTER_API_KEY=...` in `%LOCALAPPDATA%\hermes\.env`;
   set `model.provider: "openrouter"` and a default model in
   `%LOCALAPPDATA%\hermes\config.yaml`.
3. Copy the skill:
   `cp hermes/skills/hr-proximity/SKILL.md $LOCALAPPDATA/hermes/skills/sports/hr-proximity/`
4. Register the daily job (07:30 local, after the morning Actions sweep):

   ```
   hermes cron create "30 7 * * *" "Do the daily run exactly as the hr-proximity skill describes: git pull, run the pipeline, write docs/data/analysis.json, commit and push, then produce the digest." --name hr-daily --skill hr-proximity --workdir C:\Users\andre\flyout-trends --deliver local
   ```

5. Optional messaging digest: run `hermes gateway` setup for Telegram/Discord
   and change `--deliver local` to your platform.

## Ad hoc use

```
hermes -z "who is most likely to homer today and why?" --skill hr-proximity
```
