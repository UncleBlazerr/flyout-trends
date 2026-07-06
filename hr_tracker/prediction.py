"""HR expectancy: day-over-day persistence and the "Most Likely to Homer" list.

Everything here reads the per-player per-day rollup (store.read_player_days());
raw event files are never re-scanned. Two signals per player:

- expectancy_score (0-100, heuristic): streak of qualifying days + qualifying
  frequency + intensity slopes (EV / would-be-HR parks / near-HR count rising).
- empirical band rate: of all historical player-days whose score fell in the
  same band, how often did an HR follow within horizon_days. Self-calibrates
  as stored history grows; hidden below min_samples.

Daily prediction records under prediction.records_dir are append-only receipts
of what was flagged, so hit rates stay measurable even if weights change later.
"""
from __future__ import annotations

import json
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import SCHEMA_VERSION
from .trends import linear_slope


def _near_hr_any(day: dict[str, Any]) -> int:
    """Per-day near-HR event count. Rollups written before the near_hr_any
    field existed fall back to the per-definition counts, capped at bbe
    (one event can carry several flags)."""
    if "near_hr_any" in day:
        return day["near_hr_any"]
    return min(day["near_hr_distance"] + day["near_hr_parks"]
               + day["near_hr_barrel"], day["bbe"])


def _weighted_near_hr(day: dict[str, Any], xbh_weight: float) -> float:
    """Near-HR count with extra-base results (doubles/triples) worth
    xbh_weight instead of 1.0 — a near-HR that already went for extra bases
    is better evidence than one caught at the track."""
    return (_near_hr_any(day)
            + (xbh_weight - 1.0) * day.get("near_hr_xbh", 0))


def _sorted_days(days: dict[str, dict], as_of: str) -> list[tuple[str, dict]]:
    return [(d, days[d]) for d in sorted(days) if d <= as_of]


def _gap(later: str, earlier: str) -> int:
    """Calendar days without an appearance between two appearance dates."""
    return (date_cls.fromisoformat(later) - date_cls.fromisoformat(earlier)).days - 1


def compute_streak(days: dict[str, dict], as_of: str,
                   config: dict[str, Any]) -> int:
    """Consecutive qualifying appearance days ending at the player's most
    recent appearance. Rest-day gaps <= max_gap_days don't break the streak;
    a non-qualifying appearance day (or a stale last appearance) does."""
    cfg = config["prediction"]
    seq = _sorted_days(days, as_of)
    if not seq:
        return 0
    if _gap(as_of, seq[-1][0]) >= cfg["max_gap_days"]:
        return 0  # hasn't appeared recently enough to be "on" a streak
    streak = 0
    prev: str | None = None
    for d, day in reversed(seq):
        if prev is not None and _gap(prev, d) > cfg["max_gap_days"]:
            break
        if _near_hr_any(day) < cfg["min_near_hr_events"]:
            break
        streak += 1
        prev = d
    return streak


def player_form(days: dict[str, dict], as_of: str,
                config: dict[str, Any]) -> dict[str, Any]:
    """Streak, qualifying frequency, intensity slopes, and expectancy score
    for one player as of a date, using only days <= as_of."""
    cfg = config["prediction"]
    seq = _sorted_days(days, as_of)
    recent = seq[-cfg["slope_window"]:]

    series = {
        "max_ev": [d["max_ev"] for _, d in recent],
        "parks_sum": [d["would_be_hr_parks_sum"] for _, d in recent],
        "near_hr": [_weighted_near_hr(d, cfg["xbh_weight"]) for _, d in recent],
    }
    slopes = {k: round(linear_slope(v), 3) for k, v in series.items()}

    streak = compute_streak(days, as_of, config)
    qualifying = sum(1 for _, d in recent
                     if _near_hr_any(d) >= cfg["min_near_hr_events"])
    frequency = qualifying / len(recent) if recent else 0.0

    scales = cfg["intensity_scales"]
    intensity = sum(max(0.0, min(1.0, slopes[k] / scales[k]))
                    for k in slopes) / len(slopes)

    w = cfg["weights"]
    score = 100.0 * (w["streak"] * min(streak, cfg["streak_cap"]) / cfg["streak_cap"]
                     + w["frequency"] * frequency
                     + w["intensity"] * intensity)
    return {
        "streak": streak,
        "frequency": round(frequency, 3),
        "slopes": slopes,
        "intensity": round(intensity, 3),
        "expectancy_score": round(score, 1),
        "last_appearance": seq[-1][0] if seq else None,
    }


def band_label(score: float, edges: list[float]) -> str:
    if score < edges[0]:
        return f"<{edges[0]:g}"
    for lo, hi in zip(edges, edges[1:]):
        if score < hi:
            return f"{lo:g}-{hi:g}"
    return f"{edges[-1]:g}+"


def _hr_within(days: dict[str, dict], after: date_cls, horizon: int) -> bool:
    return any(days.get((after + timedelta(days=k)).isoformat(), {})
               .get("hr", 0) > 0 for k in range(1, horizon + 1))


def empirical_rates(player_days: dict[str, dict],
                    config: dict[str, Any]) -> dict[str, dict]:
    """Per score band: how often an HR followed within horizon_days across all
    stored (player, appearance-day) samples. Days too close to the newest
    stored date to have full follow-up are censored (excluded)."""
    cfg = config["prediction"]
    horizon = cfg["horizon_days"]
    all_dates = sorted({d for p in player_days.values() for d in p["days"]})
    if not all_dates:
        return {}
    latest = date_cls.fromisoformat(all_dates[-1])

    bands: dict[str, dict] = {}
    for pdata in player_days.values():
        days = pdata["days"]
        for d in days:
            dd = date_cls.fromisoformat(d)
            if dd + timedelta(days=horizon) > latest:
                continue  # censored: follow-up window extends past our data
            form = player_form(days, d, config)
            label = band_label(form["expectancy_score"], cfg["score_bands"])
            b = bands.setdefault(label, {"samples": 0, "hr_followed": 0})
            b["samples"] += 1
            b["hr_followed"] += int(_hr_within(days, dd, horizon))
    for b in bands.values():
        b["rate"] = round(b["hr_followed"] / b["samples"], 3)
    return bands


def compute_predictions(store: Any, as_of: str,
                        config: dict[str, Any]) -> dict[str, Any]:
    """The ranked "Most Likely to Homer" grouping as of a date, plus the
    empirical band table it is judged against."""
    cfg = config["prediction"]
    player_days = store.read_player_days()
    bands = empirical_rates(player_days, config)
    as_of_d = date_cls.fromisoformat(as_of)

    entries = []
    for pid, pdata in player_days.items():
        days = {d: v for d, v in pdata["days"].items() if d <= as_of}
        if not days:
            continue
        if _gap(as_of, max(days)) >= cfg["max_gap_days"]:
            continue  # not currently active
        form = player_form(days, as_of, config)
        if form["expectancy_score"] <= 0:
            continue
        label = band_label(form["expectancy_score"], cfg["score_bands"])
        band = bands.get(label)
        week_start = (as_of_d - timedelta(days=6)).isoformat()
        week = [v for d, v in days.items() if d >= week_start]
        entries.append({
            "player_id": int(pid),
            "player_name": pdata["player_name"],
            "team": pdata["team"],
            "expectancy_score": form["expectancy_score"],
            "streak": form["streak"],
            "frequency": form["frequency"],
            "slopes": form["slopes"],
            "near_hr_7d": sum(_near_hr_any(v) for v in week),
            "near_hr_xbh_7d": sum(v.get("near_hr_xbh", 0) for v in week),
            "hr_7d": sum(v.get("hr", 0) for v in week),
            "max_ev_7d": round(max((v["max_ev"] for v in week), default=0.0), 1),
            "max_distance_7d": round(max((v.get("max_distance", 0.0)
                                          for v in week), default=0.0)),
            "band": label,
            "band_rate": (band["rate"] if band
                          and band["samples"] >= cfg["min_samples"] else None),
            "band_samples": band["samples"] if band else 0,
        })

    entries.sort(key=lambda e: (e["expectancy_score"], e["near_hr_7d"]),
                 reverse=True)
    return {
        "as_of": as_of,
        "horizon_days": cfg["horizon_days"],
        "min_samples": cfg["min_samples"],
        "players": entries[:cfg["top_n"]],
        "bands": bands,
    }


def write_prediction_record(records_dir: str | Path,
                            predictions: dict[str, Any],
                            config: dict[str, Any]) -> Path:
    """Append-only receipt of what was flagged today (re-running a date
    supersedes that date's record, mirroring write_day semantics)."""
    out = Path(records_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{predictions['as_of']}.json"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": predictions["as_of"],
        "config": config["prediction"],
        "players": predictions["players"],
    }
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


def annotate_repeats(predictions: dict[str, Any],
                     records_dir: str | Path) -> dict[str, Any]:
    """Mark players who were also on the most recent previous record —
    making the list again means another qualifying performance since being
    flagged (shown as a visual indicator on the dashboard)."""
    prior = sorted(p for p in Path(records_dir).glob("*.json")
                   if p.stem < predictions["as_of"])
    prev_ids: set[int] = set()
    if prior:
        rec = json.loads(prior[-1].read_text(encoding="utf-8"))
        prev_ids = {p["player_id"] for p in rec["players"]}
    for p in predictions["players"]:
        p["repeat"] = p["player_id"] in prev_ids
    return predictions


def cross_check(records_dir: str | Path, player_days: dict[str, dict],
                config: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
    """Model self-check for the dashboard bucket: players flagged on a recent
    record who have since homered. Only flags within horizon_days of as_of
    are shown here; older ones live in the aggregate track record."""
    cfg = config["prediction"]
    horizon = cfg["horizon_days"]
    as_of_d = date_cls.fromisoformat(as_of)

    hits: dict[int, dict[str, Any]] = {}
    for path in sorted(Path(records_dir).glob("*.json")):
        d = date_cls.fromisoformat(path.stem)
        if path.stem >= as_of or (as_of_d - d).days > horizon:
            continue
        rec = json.loads(path.read_text(encoding="utf-8"))
        for p in rec["players"]:
            days = player_days.get(str(p["player_id"]), {}).get("days", {})
            for k in range(1, horizon + 1):
                hr_day = (d + timedelta(days=k)).isoformat()
                if hr_day > as_of:
                    break
                hrs = days.get(hr_day, {}).get("hr", 0)
                if hrs > 0:
                    hits[p["player_id"]] = {
                        "player_id": p["player_id"],
                        "player_name": p["player_name"],
                        "team": p["team"],
                        "flagged_on": rec["as_of"],
                        "flagged_score": p["expectancy_score"],
                        "hr_on": hr_day,
                        "hr_count": hrs,
                    }
                    break
    return sorted(hits.values(),
                  key=lambda h: (h["hr_on"], h["flagged_score"]), reverse=True)


def consistency_leaderboard(records_dir: str | Path, player_days: dict[str, dict],
                            config: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
    """Players who keep re-qualifying for the Most-Likely list pull after pull —
    distinct from a single day's Top N, which only shows today's ranking.
    Ranked by the player's current run of *consecutive* prediction records they
    appear on (ending at the most recent record), then by lifetime flag count.
    Only players flagged on the most recent record are included — this is a
    "who's hot right now" view, not a historical hall of fame."""
    cfg = config["prediction"]
    paths = sorted(p for p in Path(records_dir).glob("*.json") if p.stem <= as_of)
    if not paths:
        return []
    record_dates = [p.stem for p in paths]
    date_index = {d: i for i, d in enumerate(record_dates)}
    last_idx = len(record_dates) - 1

    per_player: dict[int, dict[str, Any]] = {}
    for path in paths:
        rec = json.loads(path.read_text(encoding="utf-8"))
        idx = date_index[rec["as_of"]]
        for p in rec["players"]:
            pid = p["player_id"]
            entry = per_player.setdefault(pid, {
                "player_name": p["player_name"], "team": p["team"], "scores": {}})
            entry["player_name"] = p["player_name"]
            entry["team"] = p["team"]
            entry["scores"][idx] = p["expectancy_score"]

    out = []
    for pid, entry in per_player.items():
        idxs = sorted(entry["scores"])
        if idxs[-1] != last_idx:
            continue  # not on the most recent pull; not currently consistent
        streak = 0
        expected = last_idx
        for i in reversed(idxs):
            if i != expected:
                break
            streak += 1
            expected -= 1
        days = player_days.get(str(pid), {}).get("days", {})
        form = player_form(days, as_of, config) if days else None
        out.append({
            "player_id": pid,
            "player_name": entry["player_name"],
            "team": entry["team"],
            "record_streak": streak,
            "total_flags": len(idxs),
            "avg_score": round(sum(entry["scores"].values()) / len(idxs), 1),
            "current_score": entry["scores"][last_idx],
            "game_streak": form["streak"] if form else 0,
        })
    out.sort(key=lambda e: (e["record_streak"], e["total_flags"], e["avg_score"]),
             reverse=True)
    return out[:cfg.get("consistency_top_n", cfg["top_n"])]


def resolve_prediction_records(records_dir: str | Path,
                               player_days: dict[str, dict],
                               config: dict[str, Any]) -> dict[str, Any] | None:
    """Score past prediction records against what actually happened. Only
    records old enough for a full follow-up window are resolved. Returns None
    until at least one record resolves."""
    cfg = config["prediction"]
    horizon = cfg["horizon_days"]
    all_dates = sorted({d for p in player_days.values() for d in p["days"]})
    if not all_dates:
        return None
    latest = date_cls.fromisoformat(all_dates[-1])
    top_band = f"{cfg['score_bands'][-1]:g}+"

    overall = {"flagged": 0, "hr_followed": 0}
    top = {"flagged": 0, "hr_followed": 0}
    resolved = 0
    for path in sorted(Path(records_dir).glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        d = date_cls.fromisoformat(rec["as_of"])
        if d + timedelta(days=horizon) > latest:
            continue
        resolved += 1
        for p in rec["players"]:
            days = player_days.get(str(p["player_id"]), {}).get("days", {})
            hit = _hr_within(days, d, horizon)
            overall["flagged"] += 1
            overall["hr_followed"] += int(hit)
            if p.get("band") == top_band:
                top["flagged"] += 1
                top["hr_followed"] += int(hit)

    if resolved == 0:
        return None
    for agg in (overall, top):
        agg["rate"] = (round(agg["hr_followed"] / agg["flagged"], 3)
                       if agg["flagged"] else None)
    return {"resolved_records": resolved, "horizon_days": horizon,
            "overall": overall, "top_band": {"band": top_band, **top}}
