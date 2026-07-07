"""League-wide HR-vs-weather correlation table (PRD §6.7).

Reads the per-player per-day rollup (store.read_player_days()) — raw event
files are never re-scanned — and buckets every player-day into temperature
band x wind class cells, plus a single dome/roof-closed row. Three measures
per cell: HR-day rate, near-HR-day rate, and near-HR -> HR follow-through
within horizon_days (the same follow-up definition prediction is graded on).
Rates hide behind weather.min_samples so the dashboard can show "collecting
data" instead of noise; this table is what eventually justifies (or refutes)
the rule-of-thumb weather_factor weights.
"""
from __future__ import annotations

from datetime import date as date_cls, timedelta
from typing import Any

from .prediction import _hr_within, _near_hr_any, band_label

# cross / calm / varies winds collapse into "neutral": only a confirmed
# out- or in-blowing wind is a directional signal worth its own column.
WIND_CLASSES = ("out", "in", "neutral")


def _new_cell() -> dict[str, Any]:
    return {"player_days": 0, "hr_days": 0, "hr_total": 0, "near_hr_days": 0,
            "follow_samples": 0, "hr_followed": 0}


def _tally(cell: dict[str, Any], days: dict[str, dict], d: str,
           day: dict[str, Any], latest: date_cls | None, horizon: int) -> None:
    cell["player_days"] += 1
    hr = day.get("hr", 0)
    cell["hr_days"] += int(hr > 0)
    cell["hr_total"] += hr
    if _near_hr_any(day) > 0:
        cell["near_hr_days"] += 1
        dd = date_cls.fromisoformat(d)
        # Censor near-HR days whose follow-up window extends past our data.
        if latest is not None and dd + timedelta(days=horizon) <= latest:
            cell["follow_samples"] += 1
            cell["hr_followed"] += int(_hr_within(days, dd, horizon))


def _with_rates(cell: dict[str, Any], min_samples: int) -> dict[str, Any]:
    n = cell["player_days"]
    shown = n >= min_samples
    cell["hr_rate"] = round(cell["hr_days"] / n, 3) if shown else None
    cell["near_hr_rate"] = round(cell["near_hr_days"] / n, 3) if shown else None
    fs = cell["follow_samples"]
    cell["follow_rate"] = (round(cell["hr_followed"] / fs, 3)
                           if fs >= min_samples else None)
    return cell


def temp_band_labels(edges: list[float]) -> list[str]:
    return ([f"<{edges[0]:g}"]
            + [f"{lo:g}-{hi:g}" for lo, hi in zip(edges, edges[1:])]
            + [f"{edges[-1]:g}+"])


def weather_correlation(player_days: dict[str, dict], config: dict[str, Any],
                        as_of: str | None = None) -> dict[str, Any]:
    """Aggregate every rollup player-day into weather cells.

    Dome/closed-roof days (weather_condition in weather.neutral_conditions)
    get their own row regardless of reported temp/wind; days with no weather
    at all are only counted, never bucketed — never guess.
    """
    pcfg = config["prediction"]
    wcfg = pcfg["weather"]
    horizon = pcfg["horizon_days"]
    edges = wcfg["temp_bands"]
    min_samples = wcfg["min_samples"]
    neutral_conditions = set(wcfg["neutral_conditions"])

    all_dates = sorted({d for p in player_days.values() for d in p["days"]})
    latest = date_cls.fromisoformat(all_dates[-1]) if all_dates else None

    cells: dict[tuple[str, str], dict[str, Any]] = {}
    dome = _new_cell()
    unknown = _new_cell()
    for pdata in player_days.values():
        days = pdata["days"]
        for d, day in days.items():
            condition = day.get("weather_condition") or ""
            temp = day.get("temp_f")
            if condition in neutral_conditions:
                cell = dome
            elif temp is None:
                cell = unknown
            else:
                wind = day.get("wind_dir")
                wind_class = wind if wind in ("out", "in") else "neutral"
                cell = cells.setdefault(
                    (band_label(temp, edges), wind_class), _new_cell())
            _tally(cell, days, d, day, latest, horizon)

    ordered = [{"temp_band": tb, "wind": wc,
                **_with_rates(cells[(tb, wc)], min_samples)}
               for tb in temp_band_labels(edges)
               for wc in WIND_CLASSES
               if (tb, wc) in cells]
    return {
        "as_of": as_of or (all_dates[-1] if all_dates else None),
        "horizon_days": horizon,
        "temp_bands": edges,
        "min_samples": min_samples,
        "cells": ordered,
        "dome": _with_rates(dome, min_samples),
        "unknown_player_days": unknown["player_days"],
    }
