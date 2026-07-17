---
type: Documentation Index
title: "OpenWiki"
description: "Files and subdirectories in OpenWiki."
---

# Files

- [Architecture](architecture.md) - Pipeline architecture for the Daily HR-Proximity Tracker — linear data pipeline with one CLI entrypoint, module-per-stage design, and shared code path for Actions, local, and agent runs.
- [Data & Storage](data-and-storage.md) - Data flow and storage model for the Daily HR-Proximity Tracker — raw per-date JSON files, player index rollup, prediction receipts, EventStore protocol, and published dashboard JSON.
- [Integrations](integrations.md) - Agent skills, subagents, and LLM integrations layered on top of the HR-Proximity Tracker pipeline — Claude Code skill, savant-analyst subagent, and Hermes-agent integration.
- [Operations](operations.md) - How the Daily HR-Proximity Tracker pipeline runs in production and locally, plus CI/CD, testing, deployment, git conventions, and the OpenWiki update workflow.
- [Quickstart — Daily HR-Proximity Tracker](quickstart.md) - Entry point for the Daily HR-Proximity Tracker (flyout-trends) wiki. Explains what the pipeline does, how to run it, the repository layout, and links to all major documentation sections.
- [Scoring & Prediction](scoring-and-prediction.md) - Near-HR scoring definitions, expectancy model, weather adjustment, empirical follow-up rates, and self-checking receipts for the Daily HR-Proximity Tracker.
