"""Fetch the MLB schedule and Baseball Savant gamefeeds, parse batted-ball events."""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests

from .models import BattedBallEvent

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
GAMEFEED_URL = "https://baseballsavant.mlb.com/gf"
LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

FINAL_STATUS_CODES = {"F", "O"}  # Final, Game Over

logger = logging.getLogger(__name__)

# MLB weather `wind` phrases -> direction class. Only "out" earns a boost
# downstream; the vocabulary is observed, not contractual, so anything
# unrecognized classifies as "varies" (neutral).
_WIND_DIR_CLASSES = [
    ("out to", "out"),
    ("in from", "in"),
    ("l to r", "cross"),
    ("r to l", "cross"),
    ("calm", "none"),
    ("none", "none"),
    ("varies", "varies"),
]

_WEATHER_KEYS = ("venue_id", "venue_name", "temp_f", "wind_mph", "wind_dir",
                 "weather_condition")


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


def parse_wind(wind: Any) -> tuple[Optional[float], Optional[str]]:
    """Parse an MLB weather wind string ('5 mph, Out To CF') into (mph, class).

    The direction arrives already park-relative, so no orientation math is
    needed. Returns (None, None) when the feed omitted wind entirely.
    """
    if not wind or not isinstance(wind, str):
        return None, None
    speed_part, _, dir_part = (p.strip() for p in wind.partition(","))
    mph = _num(speed_part.lower().replace("mph", "").strip())
    direction = dir_part.lower()
    for phrase, cls in _WIND_DIR_CLASSES:
        if direction.startswith(phrase):
            return mph, cls
    logger.warning("Unrecognized wind direction %r; classifying as varies", wind)
    return mph, "varies"


def _parse_weather(weather: dict[str, Any] | None,
                   venue: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a statsapi weather/venue pair into BattedBallEvent fields.

    `temp` is a string in the feed (same numbers-as-strings gotcha as Savant).
    An empty weather object yields all-None/"" fields, which downstream
    consumers treat as neutral.
    """
    weather = weather or {}
    venue = venue or {}
    wind_mph, wind_dir = parse_wind(weather.get("wind"))
    return {
        "venue_id": venue.get("id"),
        "venue_name": venue.get("name", "") or "",
        "temp_f": _num(weather.get("temp")),
        "wind_mph": wind_mph,
        "wind_dir": wind_dir,
        "weather_condition": weather.get("condition", "") or "",
    }


def _team_abbrev(g: dict[str, Any], side: str) -> str:
    return (g.get("teams", {}).get(side, {}).get("team", {})
            or {}).get("abbreviation", "") or ""


def fetch_schedule(date: str, session: requests.Session,
                   http_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Return [{game_pk, status_code, status, home/away team, venue/weather
    fields}] for every MLB game on `date`. hydrate=weather adds the per-game
    weather object (condition/temp/wind) to the one slate-wide call — it can
    be empty for games far from first pitch — and hydrate=team exposes team
    abbreviations (which match the Savant team codes stored in the rollup)."""
    data = _get_json(session, SCHEDULE_URL,
                     {"sportId": 1, "date": date, "hydrate": "weather,team"},
                     http_cfg)
    games = []
    for day in data.get("dates", []):
        for g in day.get("games", []):
            games.append({
                "game_pk": g["gamePk"],
                "status_code": g.get("status", {}).get("statusCode", ""),
                "status": g.get("status", {}).get("detailedState", ""),
                "home_team": _team_abbrev(g, "home"),
                "away_team": _team_abbrev(g, "away"),
                **_parse_weather(g.get("weather"), g.get("venue")),
            })
    return games


def fetch_live_weather(game_pk: int, session: requests.Session,
                       http_cfg: dict[str, Any]) -> dict[str, Any]:
    """Fallback: pull gameData.weather from the live feed for one game.

    Used when the hydrated schedule returned an empty weather object for a
    final game. `fields` trims the otherwise multi-MB response to weather only.
    """
    data = _get_json(session, LIVE_FEED_URL.format(game_pk=game_pk),
                     {"fields": "gameData,weather,condition,temp,wind"}, http_cfg)
    weather = data.get("gameData", {}).get("weather") or {}
    wind_mph, wind_dir = parse_wind(weather.get("wind"))
    return {
        "temp_f": _num(weather.get("temp")),
        "wind_mph": wind_mph,
        "wind_dir": wind_dir,
        "weather_condition": weather.get("condition", "") or "",
    }


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


def _attach_weather(events: list[BattedBallEvent], game: dict[str, Any],
                    session: requests.Session, http_cfg: dict[str, Any]) -> None:
    """Stamp a game's venue/weather onto its events.

    If the hydrated schedule had no weather for a final game (rare), fall back
    to that game's live feed; if that also has none, the fields stay
    None/"" (neutral) — never guess.
    """
    meta = {k: game.get(k) for k in _WEATHER_KEYS}
    if meta["temp_f"] is None and not meta["weather_condition"]:
        try:
            meta.update(fetch_live_weather(game["game_pk"], session, http_cfg))
        except RuntimeError:
            logger.warning("No weather available for game %s", game["game_pk"])
    for event in events:
        for key, value in meta.items():
            setattr(event, key, value)


def upcoming_team_weather(date: str, config: dict[str, Any],
                          session: requests.Session | None = None
                          ) -> dict[str, dict[str, Any]]:
    """Map each team playing on `date` to its game's venue + weather, for the
    prediction stage (the ranking's follow-up window starts on `date`).

    Games far from first pitch usually have an empty schedule weather object;
    try the live feed then, and leave the fields None/"" (neutral) if that is
    empty too — never guess. A team's first game of the day wins for
    doubleheaders.
    """
    own_session = session is None
    session = session or requests.Session()
    http_cfg = config.get("http", {})
    try:
        teams: dict[str, dict[str, Any]] = {}
        for game in fetch_schedule(date, session, http_cfg):
            wx = {k: game.get(k) for k in _WEATHER_KEYS}
            if wx["temp_f"] is None and not wx["weather_condition"]:
                try:
                    wx.update(fetch_live_weather(game["game_pk"], session,
                                                 http_cfg))
                except RuntimeError:
                    pass
            for team in (game["home_team"], game["away_team"]):
                if team:
                    teams.setdefault(team, wx)
        return teams
    finally:
        if own_session:
            session.close()


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
                game_events = parse_events(feed, date)
                _attach_weather(game_events, game, session, http_cfg)
                events.extend(game_events)
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
