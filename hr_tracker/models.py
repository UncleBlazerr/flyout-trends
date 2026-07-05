"""Core data models and config loading."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

import yaml

SCHEMA_VERSION = 1


@dataclass
class BattedBallEvent:
    game_pk: int
    date: str  # YYYY-MM-DD
    player_id: int
    player_name: str
    team: str
    opponent: str
    result: str
    exit_velocity: Optional[float]
    launch_angle: Optional[float]
    hit_distance: Optional[float]
    hc_x: Optional[float]
    hc_y: Optional[float]
    # Park-adjusted would-be-HR park count straight from Savant
    # (contextMetrics.homeRunBallparks); None when the feed omits it.
    would_be_hr_count: Optional[int] = None
    inning: Optional[int] = None
    play_id: Optional[str] = None
    # Scoring outputs (attached by hr_tracker.scoring)
    distance_flag: bool = False
    would_be_hr_flag: bool = False
    barrel_score: float = 0.0
    barrel_flag: bool = False

    @property
    def is_home_run(self) -> bool:
        return self.result == "Home Run"

    @property
    def is_near_hr(self) -> bool:
        return self.distance_flag or self.would_be_hr_flag or self.barrel_flag

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["is_home_run"] = self.is_home_run
        d["is_near_hr"] = self.is_near_hr
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BattedBallEvent":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def find_config(start: str | Path | None = None) -> dict[str, Any]:
    """Locate config.yaml at the repo root relative to this package."""
    if start is not None:
        return load_config(start)
    root = Path(__file__).resolve().parent.parent
    return load_config(root / "config.yaml")
