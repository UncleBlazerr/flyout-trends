"""Pure scoring functions: attach the three near-HR classifications to events.

All thresholds and weights come from config.yaml (near_hr section) so tuning
never requires a code change.
"""
from __future__ import annotations

from typing import Any

from .models import BattedBallEvent


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def distance_flag(event: BattedBallEvent, cfg: dict[str, Any]) -> bool:
    """Definition 1: non-HR result over the distance threshold."""
    dcfg = cfg["distance"]
    if event.result not in set(dcfg["results"]):
        return False
    return event.hit_distance is not None and event.hit_distance > dcfg["threshold_ft"]


def would_be_hr_flag(event: BattedBallEvent, cfg: dict[str, Any]) -> bool:
    """Definition 2: not a HR, but would have left >= min_parks of the 30 parks."""
    if event.is_home_run or event.would_be_hr_count is None:
        return False
    return event.would_be_hr_count >= cfg["would_be_hr"]["min_parks"]


def barrel_score(event: BattedBallEvent, cfg: dict[str, Any]) -> float:
    """Definition 3: 0-100 weighted blend of EV, launch-angle deviation, distance."""
    bcfg = cfg["barrel_score"]
    weights = bcfg["weights"]

    ev_lo, ev_hi = bcfg["exit_velocity_range"]
    ev_component = _clamp01(((event.exit_velocity or 0.0) - ev_lo) / (ev_hi - ev_lo))

    if event.launch_angle is None:
        la_component = 0.0
    else:
        deviation = abs(event.launch_angle - bcfg["ideal_launch_angle"])
        la_component = _clamp01(1.0 - deviation / bcfg["launch_angle_tolerance"])

    d_lo, d_hi = bcfg["distance_range"]
    dist_component = _clamp01(((event.hit_distance or 0.0) - d_lo) / (d_hi - d_lo))

    score = 100.0 * (
        weights["exit_velocity"] * ev_component
        + weights["launch_angle"] * la_component
        + weights["distance"] * dist_component
    )
    return round(score, 1)


def score_event(event: BattedBallEvent, config: dict[str, Any]) -> BattedBallEvent:
    """Attach all three classifications to the event (mutates and returns it)."""
    cfg = config["near_hr"]
    event.distance_flag = distance_flag(event, cfg)
    event.would_be_hr_flag = would_be_hr_flag(event, cfg)
    event.barrel_score = barrel_score(event, cfg)
    event.barrel_flag = (not event.is_home_run
                         and event.barrel_score >= cfg["barrel_score"]["min_score"])
    return event


def score_events(events: list[BattedBallEvent],
                 config: dict[str, Any]) -> list[BattedBallEvent]:
    return [score_event(e, config) for e in events]
