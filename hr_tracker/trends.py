"""Rolling per-player trend computation over the EventStore."""
from __future__ import annotations

from collections import defaultdict
from datetime import date as date_cls, timedelta
from typing import Any

from .models import BattedBallEvent
from .store import EventStore


def _linear_slope(ys: list[float]) -> float:
    """Least-squares slope of ys against x = 0..n-1."""
    n = len(ys)
    if n < 2:
        return 0.0
    xs = range(n)
    mean_x = (n - 1) / 2
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom


def _window_stats(events: list[BattedBallEvent], start: str,
                  end: str, config: dict[str, Any]) -> dict[str, Any]:
    window_events = [e for e in events if start <= e.date <= end]
    near = [e for e in window_events if e.is_near_hr]
    hrs = sum(1 for e in window_events if e.is_home_run)

    # Daily would-be-HR park totals on non-HR contact drive the trend slope.
    daily_parks: dict[str, float] = defaultdict(float)
    for e in window_events:
        if not e.is_home_run and e.would_be_hr_count:
            daily_parks[e.date] += e.would_be_hr_count
    n_days = (date_cls.fromisoformat(end) - date_cls.fromisoformat(start)).days + 1
    series = [daily_parks[(date_cls.fromisoformat(start) + timedelta(days=i)).isoformat()]
              for i in range(n_days)]
    slope = round(_linear_slope(series), 3)

    flat = config["trends"].get("flat_slope", 0.05)
    direction = "flat" if abs(slope) < flat else ("rising" if slope > 0 else "falling")

    evs = [e.exit_velocity for e in near if e.exit_velocity is not None]
    return {
        "bbe": len(window_events),
        "hr": hrs,
        "near_hr_distance": sum(1 for e in window_events if e.distance_flag),
        "near_hr_parks": sum(1 for e in window_events if e.would_be_hr_flag),
        "near_hr_barrel": sum(1 for e in window_events if e.barrel_flag),
        "near_hr_any": len(near),
        "max_ev_near_hr": round(max(evs), 1) if evs else None,
        "avg_ev_near_hr": round(sum(evs) / len(evs), 1) if evs else None,
        "max_barrel_score": round(max((e.barrel_score for e in window_events),
                                      default=0.0), 1),
        "would_be_hr_parks_sum": int(sum(
            e.would_be_hr_count for e in window_events
            if not e.is_home_run and e.would_be_hr_count)),
        "parks_slope": slope,
        "trend_direction": direction,
    }


def compute_trends(store: EventStore, as_of: str,
                   config: dict[str, Any]) -> dict[str, Any]:
    """Per-player rolling stats over each configured trailing window ending at as_of."""
    windows = config["trends"]["windows"]
    heat = config["trends"]["heating_up"]
    max_window = max(windows)
    end = date_cls.fromisoformat(as_of)
    start = (end - timedelta(days=max_window - 1)).isoformat()

    by_player: dict[int, list[BattedBallEvent]] = defaultdict(list)
    for e in store.read_range(start, as_of):
        by_player[e.player_id].append(e)

    players = []
    for pid, events in by_player.items():
        latest = max(events, key=lambda e: e.date)
        entry: dict[str, Any] = {
            "player_id": pid,
            "player_name": latest.player_name,
            "team": latest.team,
            "windows": {},
        }
        for w in windows:
            w_start = (end - timedelta(days=w - 1)).isoformat()
            entry["windows"][str(w)] = _window_stats(events, w_start, as_of, config)
        heat_stats = entry["windows"].get(str(heat["window"]))
        entry["heating_up"] = bool(
            heat_stats
            and heat_stats["near_hr_any"] >= heat["min_events"]
            and heat_stats["parks_slope"] >= heat["min_slope"])
        players.append(entry)

    players.sort(key=lambda p: (
        p["windows"][str(heat["window"])]["near_hr_any"],
        p["windows"][str(heat["window"])]["max_barrel_score"]), reverse=True)
    return {"as_of": as_of, "windows": windows, "players": players}
