import copy

from hr_tracker.weather import temp_band_labels, weather_correlation


def wday(temp=88.0, wind_mph=8.0, wind_dir="out", cond="Sunny",
         near=1, hr=0, bbe=3):
    return {"bbe": bbe, "hr": hr, "near_hr_any": near, "near_hr_xbh": 0,
            "near_hr_distance": near, "near_hr_parks": 0, "near_hr_barrel": 0,
            "would_be_hr_parks_sum": 4, "max_ev": 100.0, "max_distance": 380.0,
            "max_barrel_score": 60.0, "temp_f": temp, "wind_mph": wind_mph,
            "wind_dir": wind_dir, "weather_condition": cond}


def players(days_by_pid):
    return {pid: {"player_name": f"P{pid}", "team": "PIT", "days": days}
            for pid, days in days_by_pid.items()}


def low_threshold(config, n=1):
    cfg = copy.deepcopy(config)
    cfg["prediction"]["weather"]["min_samples"] = n
    return cfg


def cell(result, temp_band, wind):
    return next(c for c in result["cells"]
                if c["temp_band"] == temp_band and c["wind"] == wind)


def test_temp_band_labels(config):
    assert temp_band_labels([55, 70, 85]) == ["<55", "55-70", "70-85", "85+"]


def test_buckets_by_temp_band_and_wind_class(config):
    data = players({"1": {
        "2026-07-01": wday(temp=90.0, wind_dir="out"),
        "2026-07-02": wday(temp=60.0, wind_dir="in"),
        "2026-07-03": wday(temp=75.0, wind_dir="cross"),   # -> neutral
        "2026-07-04": wday(temp=50.0, wind_dir="varies"),  # -> neutral
    }})
    result = weather_correlation(data, low_threshold(config), "2026-07-04")
    assert cell(result, "85+", "out")["player_days"] == 1
    assert cell(result, "55-70", "in")["player_days"] == 1
    assert cell(result, "70-85", "neutral")["player_days"] == 1
    assert cell(result, "<55", "neutral")["player_days"] == 1
    assert result["dome"]["player_days"] == 0
    assert result["unknown_player_days"] == 0


def test_dome_days_get_their_own_row(config):
    # Condition wins over temp/wind: a 72F "Dome" day must not pollute the
    # outdoor 70-85/neutral cell, whatever its reported wind.
    data = players({"1": {
        "2026-07-01": wday(temp=72.0, wind_mph=0.0, wind_dir="none",
                           cond="Dome"),
        "2026-07-02": wday(temp=73.0, wind_mph=0.0, wind_dir="none",
                           cond="Roof Closed"),
        "2026-07-03": wday(temp=72.0, wind_mph=0.0, wind_dir="none",
                           cond="Clear"),  # genuinely calm outdoor day
    }})
    result = weather_correlation(data, low_threshold(config), "2026-07-03")
    assert result["dome"]["player_days"] == 2
    assert cell(result, "70-85", "neutral")["player_days"] == 1


def test_days_without_weather_are_counted_not_bucketed(config):
    data = players({"1": {
        "2026-07-01": wday(temp=None, wind_mph=None, wind_dir=None, cond=""),
        "2026-07-02": wday(),
    }})
    result = weather_correlation(data, low_threshold(config), "2026-07-02")
    assert result["unknown_player_days"] == 1
    assert sum(c["player_days"] for c in result["cells"]) == 1


def test_follow_through_counts_and_censoring(config):
    # horizon=3. Near-HR on 07-01 followed by an HR on 07-03 -> hit.
    # Near-HR on 07-05 (latest) has no full follow-up window -> censored.
    data = players({"1": {
        "2026-07-01": wday(near=1),
        "2026-07-03": wday(near=0, hr=1),
        "2026-07-05": wday(near=1),
    }})
    result = weather_correlation(data, low_threshold(config), "2026-07-05")
    c = cell(result, "85+", "out")
    assert c["player_days"] == 3
    assert c["near_hr_days"] == 2
    assert c["follow_samples"] == 1   # 07-05 censored
    assert c["hr_followed"] == 1
    assert c["follow_rate"] == 1.0
    assert c["hr_days"] == 1 and c["hr_total"] == 1


def test_rates_hidden_below_min_samples(config):
    # Repo default min_samples (25) far exceeds one player-day.
    data = players({"1": {"2026-07-01": wday(near=1, hr=1)}})
    result = weather_correlation(data, config, "2026-07-01")
    c = cell(result, "85+", "out")
    assert c["player_days"] == 1          # counts always present
    assert c["hr_rate"] is None           # rates gated: "collecting data"
    assert c["near_hr_rate"] is None
    assert c["follow_rate"] is None


def test_empty_rollup(config):
    result = weather_correlation({}, config)
    assert result["cells"] == []
    assert result["as_of"] is None
    assert result["dome"]["player_days"] == 0
