"""EventStore protocol and the v1 flat-file implementation.

Every other component talks only to the EventStore interface; swapping in a
SQLite/Postgres backend later means implementing this protocol and replaying
data/raw/*.json through write_day().
"""
from __future__ import annotations

import json
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from .models import SCHEMA_VERSION, BattedBallEvent


class EventStore(Protocol):
    def write_day(self, date: str, events: list[BattedBallEvent]) -> None: ...
    def read_range(self, start: str, end: str) -> list[BattedBallEvent]: ...
    def read_player_history(self, player_id: int, days: int,
                            end: str | None = None) -> list[BattedBallEvent]: ...


def _iter_dates(start: str, end: str):
    d = date_cls.fromisoformat(start)
    stop = date_cls.fromisoformat(end)
    while d <= stop:
        yield d.isoformat()
        d += timedelta(days=1)


class FlatFileStore:
    """One immutable JSON file per date under raw_dir, plus an incrementally
    updated player index rollup for fast trend reads."""

    def __init__(self, raw_dir: str | Path = "data/raw",
                 rollup_dir: str | Path = "data/rollups"):
        self.raw_dir = Path(raw_dir)
        self.rollup_dir = Path(rollup_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.rollup_dir.mkdir(parents=True, exist_ok=True)

    def _raw_path(self, date: str) -> Path:
        return self.raw_dir / f"{date}.json"

    @property
    def _index_path(self) -> Path:
        return self.rollup_dir / "player_index.json"

    def write_day(self, date: str, events: list[BattedBallEvent]) -> None:
        """Write the full day's events. Re-running the same date replaces that
        date's file (a full re-ingest supersedes it); other dates are never touched."""
        payload = {
            "schema_version": SCHEMA_VERSION,
            "date": date,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "events": [e.to_dict() for e in events],
        }
        self._raw_path(date).write_text(
            json.dumps(payload, indent=1), encoding="utf-8")
        self._update_rollup(date, events)

    def read_day(self, date: str) -> list[BattedBallEvent]:
        path = self._raw_path(date)
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [BattedBallEvent.from_dict(d) for d in payload.get("events", [])]

    def read_range(self, start: str, end: str) -> list[BattedBallEvent]:
        events: list[BattedBallEvent] = []
        for date in _iter_dates(start, end):
            events.extend(self.read_day(date))
        return events

    def read_player_history(self, player_id: int, days: int,
                            end: str | None = None) -> list[BattedBallEvent]:
        end_date = date_cls.fromisoformat(end) if end else date_cls.today()
        start = (end_date - timedelta(days=days - 1)).isoformat()
        return [e for e in self.read_range(start, end_date.isoformat())
                if e.player_id == player_id]

    def available_dates(self) -> list[str]:
        return sorted(p.stem for p in self.raw_dir.glob("*.json"))

    def _update_rollup(self, date: str, events: list[BattedBallEvent]) -> None:
        """Replace this date's per-player daily summaries in player_index.json."""
        index = {"schema_version": SCHEMA_VERSION, "players": {}}
        if self._index_path.exists():
            index = json.loads(self._index_path.read_text(encoding="utf-8"))
        players = index.setdefault("players", {})

        # Drop any previous entries for this date (re-ingest supersedes them).
        for pdata in players.values():
            pdata.get("days", {}).pop(date, None)

        for e in events:
            pdata = players.setdefault(str(e.player_id), {
                "player_name": e.player_name, "team": e.team, "days": {}})
            pdata["player_name"] = e.player_name
            pdata["team"] = e.team
            day = pdata["days"].setdefault(date, {
                "bbe": 0, "hr": 0, "near_hr_distance": 0, "near_hr_parks": 0,
                "near_hr_barrel": 0, "would_be_hr_parks_sum": 0,
                "max_ev": 0.0, "max_barrel_score": 0.0})
            day["bbe"] += 1
            day["hr"] += int(e.is_home_run)
            day["near_hr_distance"] += int(e.distance_flag)
            day["near_hr_parks"] += int(e.would_be_hr_flag)
            day["near_hr_barrel"] += int(e.barrel_flag)
            if not e.is_home_run and e.would_be_hr_count:
                day["would_be_hr_parks_sum"] += e.would_be_hr_count
            day["max_ev"] = max(day["max_ev"], e.exit_velocity or 0.0)
            day["max_barrel_score"] = max(day["max_barrel_score"], e.barrel_score)

        # Prune players whose every day was removed.
        index["players"] = {pid: p for pid, p in players.items() if p.get("days")}
        self._index_path.write_text(
            json.dumps(index, indent=1), encoding="utf-8")
