from hr_tracker.ingest import parse_events

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
