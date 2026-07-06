import pytest

from hr_tracker.ingest import (GAMEFEED_URL, SCHEDULE_URL, fetch_schedule,
                               ingest_date, parse_events, parse_wind)

# Trimmed real-shape sample from baseballsavant.mlb.com/gf (numbers-as-strings included)
SAMPLE_GF = {
    "exit_velocity": [
        {   # normal batted ball
            "play_id": "aaa", "game_pk": "822716", "pitch_call": "hit_into_play",
            "batter": 695578, "batter_name": "James Wood",
            "team_batting": "WSH", "team_fielding": "PIT",
            "result": "Flyout", "launch_speed": "104.3", "launch_angle": "31",
            "hit_distance": "391", "hc_x": 120.5, "hc_y": 60.2, "inning": 3,
            "contextMetrics": {"homeRunBallparks": 12},
        },
        {   # non-BIP entry (foul etc.) must be skipped
            "play_id": "bbb", "game_pk": "822716", "pitch_call": "foul",
            "batter": 1, "batter_name": "X", "launch_speed": "90.0",
        },
        {   # missing EV must be skipped
            "play_id": "ccc", "game_pk": "822716", "pitch_call": "hit_into_play",
            "batter": 2, "batter_name": "Y", "launch_speed": None,
        },
        {   # duplicate play_id must be deduped
            "play_id": "aaa", "game_pk": "822716", "pitch_call": "hit_into_play",
            "batter": 695578, "batter_name": "James Wood",
            "team_batting": "WSH", "team_fielding": "PIT",
            "result": "Flyout", "launch_speed": "104.3",
        },
        {   # no contextMetrics -> would_be_hr_count None; blank distance -> None
            "play_id": "ddd", "game_pk": "822716", "pitch_call": "hit_into_play",
            "batter": 668804, "batter_name": "Bryan Reynolds",
            "team_batting": "PIT", "team_fielding": "WSH",
            "result": "Single", "launch_speed": "83.0", "launch_angle": "10",
            "hit_distance": "", "hc_x": 99.6, "hc_y": 152.7, "inning": 1,
        },
    ]
}


def test_parse_events_shapes_and_filters():
    events = parse_events(SAMPLE_GF, "2026-07-04")
    assert len(events) == 2

    wood = events[0]
    assert wood.player_id == 695578
    assert wood.game_pk == 822716
    assert wood.date == "2026-07-04"
    assert wood.team == "WSH" and wood.opponent == "PIT"
    assert wood.exit_velocity == 104.3          # string -> float
    assert wood.launch_angle == 31.0
    assert wood.hit_distance == 391.0
    assert wood.would_be_hr_count == 12

    reynolds = events[1]
    assert reynolds.hit_distance is None
    assert reynolds.would_be_hr_count is None


def test_roundtrip_to_dict_from_dict():
    from hr_tracker.models import BattedBallEvent
    events = parse_events(SAMPLE_GF, "2026-07-04")
    restored = BattedBallEvent.from_dict(events[0].to_dict())
    assert restored == events[0]


# --- Weather ---------------------------------------------------------------

# Trimmed real-shape sample from statsapi schedule?hydrate=weather:
# populated outdoor game, dome game, and an empty weather object.
SAMPLE_SCHEDULE = {
    "dates": [{
        "games": [
            {
                "gamePk": 824902,
                "status": {"statusCode": "F", "detailedState": "Final"},
                "venue": {"id": 4705, "name": "Truist Park"},
                "weather": {"condition": "Partly Cloudy", "temp": "89",
                            "wind": "5 mph, Out To LF"},
            },
            {
                "gamePk": 822958,
                "status": {"statusCode": "F", "detailedState": "Final"},
                "venue": {"id": 12, "name": "Tropicana Field"},
                "weather": {"condition": "Dome", "temp": "72",
                            "wind": "0 mph, None"},
            },
            {
                "gamePk": 823282,
                "status": {"statusCode": "S", "detailedState": "Scheduled"},
                "venue": {"id": 2680, "name": "Petco Park"},
                "weather": {},
            },
        ],
    }]
}


@pytest.mark.parametrize("wind, expected", [
    ("5 mph, Out To CF", (5.0, "out")),
    ("12 mph, Out To LF", (12.0, "out")),
    ("8 mph, In From RF", (8.0, "in")),
    ("4 mph, L To R", (4.0, "cross")),
    ("6 mph, R To L", (6.0, "cross")),
    ("0 mph, Calm", (0.0, "none")),
    ("0 mph, None", (0.0, "none")),
    ("7 mph, Varies", (7.0, "varies")),
    ("3 mph, Swirling", (3.0, "varies")),   # unrecognized phrasing -> neutral
    ("gusty", (None, "varies")),            # no speed, no known direction
    ("", (None, None)),
    (None, (None, None)),
])
def test_parse_wind(wind, expected):
    assert parse_wind(wind) == expected


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    """Routes schedule/gamefeed/live-feed GETs to canned payloads."""

    def __init__(self, responses):
        self.responses = responses  # url (or (url, game_pk)) -> payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params or {}))
        key = (url, (params or {}).get("game_pk", None))
        payload = self.responses.get(key, self.responses.get(url))
        if payload is None:
            raise KeyError(f"unexpected fetch: {url} {params}")
        return FakeResponse(payload)

    def close(self):
        pass


def test_fetch_schedule_hydrates_weather():
    session = FakeSession({SCHEDULE_URL: SAMPLE_SCHEDULE})
    games = fetch_schedule("2026-07-05", session, {})

    url, params = session.calls[0]
    assert params["hydrate"] == "weather"

    outdoor, dome, empty = games
    assert outdoor["venue_id"] == 4705 and outdoor["venue_name"] == "Truist Park"
    assert outdoor["temp_f"] == 89.0            # string -> float
    assert outdoor["wind_mph"] == 5.0 and outdoor["wind_dir"] == "out"
    assert outdoor["weather_condition"] == "Partly Cloudy"

    assert dome["weather_condition"] == "Dome"
    assert dome["wind_mph"] == 0.0 and dome["wind_dir"] == "none"

    assert empty["temp_f"] is None and empty["wind_dir"] is None
    assert empty["weather_condition"] == ""


def test_ingest_date_stamps_weather_onto_events():
    schedule = {"dates": [{"games": [{
        "gamePk": 822716,
        "status": {"statusCode": "F", "detailedState": "Final"},
        "venue": {"id": 3309, "name": "Nationals Park"},
        "weather": {"condition": "Overcast", "temp": "86",
                    "wind": "9 mph, Out To CF"},
    }]}]}
    session = FakeSession({
        SCHEDULE_URL: schedule,
        (GAMEFEED_URL, 822716): SAMPLE_GF,
    })
    events, summary = ingest_date("2026-07-04", {}, session=session)

    assert summary["games_processed"] == 1
    assert len(events) == 2
    for e in events:
        assert e.venue_id == 3309 and e.venue_name == "Nationals Park"
        assert e.temp_f == 86.0
        assert e.wind_mph == 9.0 and e.wind_dir == "out"
        assert e.weather_condition == "Overcast"
    # no live-feed fallback call was needed
    assert all(GAMEFEED_URL in url or url == SCHEDULE_URL
               for url, _ in session.calls)


def test_ingest_date_falls_back_to_live_feed_for_empty_weather():
    schedule = {"dates": [{"games": [{
        "gamePk": 822716,
        "status": {"statusCode": "F", "detailedState": "Final"},
        "venue": {"id": 3309, "name": "Nationals Park"},
        "weather": {},
    }]}]}
    live_feed = {"gameData": {"weather": {
        "condition": "Sunny", "temp": "91", "wind": "11 mph, In From LF"}}}
    session = FakeSession({
        SCHEDULE_URL: schedule,
        (GAMEFEED_URL, 822716): SAMPLE_GF,
        "https://statsapi.mlb.com/api/v1.1/game/822716/feed/live": live_feed,
    })
    events, _ = ingest_date("2026-07-04", {}, session=session)

    for e in events:
        assert e.temp_f == 91.0
        assert e.wind_mph == 11.0 and e.wind_dir == "in"
        assert e.weather_condition == "Sunny"
        # venue still comes from the schedule
        assert e.venue_id == 3309
