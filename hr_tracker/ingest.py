"""Fetch the MLB schedule and Baseball Savant gamefeeds, parse batted-ball events."""
from __future__ import annotations

import time
from typing import Any, Optional

import requests

from .models import BattedBallEvent

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
GAMEFEED_URL = "https://baseballsavant.mlb.com/gf"

FINAL_STATUS_CODES = {"F", "O"}  # Final, Game Over


def _get_json(session: requests.Session, url: str, params: dict[str, Any],
              http_cfg: dict[str, Any]) -> Any:
    timeout = http_cfg.get("timeout", 30)
    retries = http_cfg.get("retries", 3)
    backoff = http_cfg.get("backoff_seconds", 2.0)
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts") from last_exc


def fetch_schedule(date: str, session: requests.Session,
                   http_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Return [{game_pk, status_code, status}] for every MLB game on `date`."""
    data = _get_json(session, SCHEDULE_URL, {"sportId": 1, "date": date}, http_cfg)
    games = []
    for day in data.get("dates", []):
        for g in day.get("games", []):
            games.append({
                "game_pk": g["gamePk"],
                "status_code": g.get("status", {}).get("statusCode", ""),
                "status": g.get("status", {}).get("detailedState", ""),
            })
    return games


def fetch_gamefeed(game_pk: int, session: requests.Session,
                   http_cfg: dict[str, Any]) -> dict[str, Any]:
    return _get_json(session, GAMEFEED_URL, {"game_pk": game_pk}, http_cfg)


def _num(value: Any) -> Optional[float]:
    """Savant serves numeric fields as strings ('113.1', '428'); parse defensively."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_events(gamefeed: dict[str, Any], date: str) -> list[BattedBallEvent]:
    """Parse the gamefeed's exit_velocity[] array into BattedBallEvents.

    Only balls put in play with a measured exit velocity are kept.
    """
    events: list[BattedBallEvent] = []
    seen: set[str] = set()
    for entry in gamefeed.get("exit_velocity") or []:
        if entry.get("pitch_call") != "hit_into_play":
            continue
        ev = _num(entry.get("launch_speed") or entry.get("hit_speed"))
        if ev is None:
            continue
        play_id = entry.get("play_id") or entry.get("rowId")
        if play_id in seen:
            continue
        seen.add(play_id)
        context = entry.get("contextMetrics") or {}
        parks = context.get("homeRunBallparks")
        distance = _num(entry.get("hit_distance"))
        events.append(BattedBallEvent(
            game_pk=int(entry.get("game_pk") or gamefeed.get("scoreboard", {}).get("gamePk", 0)),
            date=date,
            player_id=int(entry["batter"]),
            player_name=entry.get("batter_name", ""),
            team=entry.get("team_batting", ""),
            opponent=entry.get("team_fielding", ""),
            result=entry.get("result", ""),
            exit_velocity=ev,
            launch_angle=_num(entry.get("launch_angle") or entry.get("hit_angle")),
            hit_distance=distance,
            hc_x=_num(entry.get("hc_x")),
            hc_y=_num(entry.get("hc_y")),
            would_be_hr_count=int(parks) if parks is not None else None,
            inning=entry.get("inning"),
            play_id=play_id,
        ))
    return events


def ingest_date(date: str, config: dict[str, Any],
                session: requests.Session | None = None,
                include_unfinished: bool = False) -> tuple[list[BattedBallEvent], dict[str, Any]]:
    """Fetch every game for `date` and return (events, summary).

    By default only games with a Final status are ingested so a day's data is
    never polluted by partial in-progress feeds.
    """
    own_session = session is None
    session = session or requests.Session()
    http_cfg = config.get("http", {})
    try:
        games = fetch_schedule(date, session, http_cfg)
        events: list[BattedBallEvent] = []
        processed, skipped, failed = [], [], []
        for game in games:
            if not include_unfinished and game["status_code"] not in FINAL_STATUS_CODES:
                skipped.append(game)
                continue
            try:
                feed = fetch_gamefeed(game["game_pk"], session, http_cfg)
                events.extend(parse_events(feed, date))
                processed.append(game)
            except RuntimeError:
                failed.append(game)
        summary = {
            "date": date,
            "games_scheduled": len(games),
            "games_processed": len(processed),
            "games_skipped_not_final": [g["game_pk"] for g in skipped],
            "games_failed": [g["game_pk"] for g in failed],
            "events": len(events),
        }
        return events, summary
    finally:
        if own_session:
            session.close()
