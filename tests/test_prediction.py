import copy
import json

from hr_tracker.prediction import (annotate_repeats, band_label,
                                   compute_predictions, compute_streak,
                                   consistency_leaderboard, cross_check,
                                   empirical_rates, player_form,
                                   resolve_prediction_records, weather_factor,
                                   write_prediction_record)


def day(near=1, hr=0, bbe=3, max_ev=100.0, parks=5, xbh=0, dist=380.0):
    return {"bbe": bbe, "hr": hr, "near_hr_any": near, "near_hr_xbh": xbh,
            "near_hr_distance": near, "near_hr_parks": 0, "near_hr_barrel": 0,
            "would_be_hr_parks_sum": parks, "max_ev": max_ev,
            "max_distance": dist, "max_barrel_score": 60.0}


class FakeStore:
    def __init__(self, players):
        self.players = players

    def read_player_days(self):
        return self.players


# ---- streak ----------------------------------------------------------------

def test_streak_counts_consecutive_qualifying_days(config):
    days = {"2026-07-02": day(), "2026-07-03": day(), "2026-07-04": day()}
    assert compute_streak(days, "2026-07-04", config) == 3


def test_streak_survives_rest_day_gap(config):
    # 2-day gap between appearances (max_gap_days=2) keeps the streak alive.
    days = {"2026-07-01": day(), "2026-07-04": day()}
    assert compute_streak(days, "2026-07-04", config) == 2


def test_streak_broken_by_long_gap(config):
    days = {"2026-06-28": day(), "2026-07-04": day()}
    assert compute_streak(days, "2026-07-04", config) == 1


def test_streak_broken_by_non_qualifying_day(config):
    days = {"2026-07-02": day(), "2026-07-03": day(near=0), "2026-07-04": day()}
    assert compute_streak(days, "2026-07-04", config) == 1


def test_streak_zero_when_last_appearance_stale(config):
    days = {"2026-07-01": day()}
    assert compute_streak(days, "2026-07-04", config) == 0


def test_streak_fallback_for_old_rollup_without_near_hr_any(config):
    legacy = {k: v for k, v in day().items() if k != "near_hr_any"}
    assert compute_streak({"2026-07-04": legacy}, "2026-07-04", config) == 1


# ---- form / score ----------------------------------------------------------

def test_score_bounds_and_max(config):
    # 5-day streak (cap), all days qualifying, strongly rising everything.
    days = {f"2026-07-0{i}": day(near=i, max_ev=90.0 + 5 * i, parks=4 * i)
            for i in range(1, 6)}
    form = player_form(days, "2026-07-05", config)
    assert form["streak"] == 5
    assert form["frequency"] == 1.0
    assert 0.0 <= form["expectancy_score"] <= 100.0
    assert form["expectancy_score"] == 100.0


def test_score_zero_for_cold_player(config):
    days = {"2026-07-03": day(near=0, max_ev=85.0, parks=0),
            "2026-07-04": day(near=0, max_ev=85.0, parks=0)}
    form = player_form(days, "2026-07-04", config)
    assert form["expectancy_score"] == 0.0


def test_form_uses_only_days_up_to_as_of(config):
    days = {"2026-07-03": day(), "2026-07-04": day(near=0),
            "2026-07-05": day(near=5, max_ev=115.0, parks=30)}
    form = player_form(days, "2026-07-04", config)
    assert form["streak"] == 0
    assert form["last_appearance"] == "2026-07-04"


def test_band_label_edges(config):
    edges = config["prediction"]["score_bands"]  # [40, 60, 80]
    assert band_label(0, edges) == "<40"
    assert band_label(39.9, edges) == "<40"
    assert band_label(40.0, edges) == "40-60"
    assert band_label(79.9, edges) == "60-80"
    assert band_label(80.0, edges) == "80+"
    assert band_label(100.0, edges) == "80+"


def test_xbh_near_hrs_outweigh_outs(config):
    # Same shape of week, but one player's near-HRs went for doubles: his
    # weighted near-HR series rises faster, so intensity (and score) is higher.
    outs = {f"2026-07-0{i}": day(near=i, xbh=0) for i in range(1, 5)}
    xbh = {f"2026-07-0{i}": day(near=i, xbh=i) for i in range(1, 5)}
    f_outs = player_form(outs, "2026-07-04", config)
    f_xbh = player_form(xbh, "2026-07-04", config)
    assert f_xbh["slopes"]["near_hr"] > f_outs["slopes"]["near_hr"]
    assert f_xbh["expectancy_score"] >= f_outs["expectancy_score"]


def test_hr_does_not_change_score(config):
    # HRs are informational: identical near-HR profile with/without a homer
    # must score the same.
    base = {f"2026-07-0{i}": day(near=1) for i in range(1, 4)}
    with_hr = {d: dict(v, hr=1) for d, v in base.items()}
    assert (player_form(base, "2026-07-03", config)["expectancy_score"]
            == player_form(with_hr, "2026-07-03", config)["expectancy_score"])


# ---- weather factor ---------------------------------------------------------

def wx(**kw):
    base = dict(venue_name="Test Park", temp_f=70.0, wind_mph=0.0,
                wind_dir="none", weather_condition="Clear")
    base.update(kw)
    return base


def test_weather_factor_neutral_cases(config):
    assert weather_factor(None, config) == 1.0
    assert weather_factor({}, config) == 1.0  # empty forecast, never guess
    assert weather_factor(wx(temp_f=None, wind_mph=None, wind_dir=None,
                             weather_condition=""), config) == 1.0
    # Domes/closed roofs are exactly neutral no matter the reported temp.
    assert weather_factor(wx(temp_f=72.0, weather_condition="Dome"),
                          config) == 1.0
    assert weather_factor(wx(temp_f=95.0, wind_mph=15.0, wind_dir="out",
                             weather_condition="Roof Closed"), config) == 1.0


def test_weather_factor_disabled_by_config(config):
    cfg = copy.deepcopy(config)
    cfg["prediction"]["weather"]["enabled"] = False
    assert weather_factor(wx(temp_f=95.0, wind_mph=15.0, wind_dir="out"),
                          cfg) == 1.0


def test_weather_factor_hot_and_wind_out_compound(config):
    # 80F -> 1.04; 10 mph out -> 1.12; compounding: 1.04 * 1.12 = 1.165
    hot = weather_factor(wx(temp_f=80.0), config)
    windy = weather_factor(wx(wind_mph=10.0, wind_dir="out"), config)
    both = weather_factor(wx(temp_f=80.0, wind_mph=10.0, wind_dir="out"),
                          config)
    assert hot == 1.04 and windy == 1.12
    assert both == 1.165  # > hot and > windy: hot + wind out is best

def test_weather_factor_out_wind_below_threshold_earns_nothing(config):
    assert weather_factor(wx(wind_mph=4.0, wind_dir="out"), config) == 1.0


def test_weather_factor_in_wind_is_penalized_not_boosted(config):
    # The wind must be blowing OUT: 10 mph in -> 1 - 0.008*10 = 0.92
    assert weather_factor(wx(wind_mph=10.0, wind_dir="in"), config) == 0.92


def test_weather_factor_cross_wind_neutral(config):
    assert weather_factor(wx(wind_mph=15.0, wind_dir="cross"), config) == 1.0
    assert weather_factor(wx(wind_mph=15.0, wind_dir="varies"), config) == 1.0


def test_weather_factor_clamped_both_ways(config):
    lo, hi = config["prediction"]["weather"]["clamp"]
    # 98F * 20mph out = 1.112 * 1.24 = 1.379 -> ceiling
    assert weather_factor(wx(temp_f=98.0, wind_mph=20.0, wind_dir="out"),
                          config) == hi
    # 40F * 20mph in = 0.88 * 0.84 = 0.739 -> floor
    assert weather_factor(wx(temp_f=40.0, wind_mph=20.0, wind_dir="in"),
                          config) == lo


def test_weather_factor_cold_is_penalty_not_veto(config):
    f = weather_factor(wx(temp_f=45.0), config)
    assert config["prediction"]["weather"]["clamp"][0] <= f < 1.0


# ---- empirical rates -------------------------------------------------------

def _history_player(hr_on_last=True):
    """Six qualifying days; HR only on the final day."""
    dates = [f"2026-07-0{i}" for i in range(1, 7)]
    return {"player_name": "Hist Guy", "team": "PIT",
            "days": {d: day(hr=int(hr_on_last and d == dates[-1]))
                     for d in dates}}


def test_empirical_rates_censor_recent_days(config):
    # horizon=3, latest=07-06: only 07-01..07-03 are old enough to label.
    players = {"1": _history_player()}
    bands = empirical_rates(players, config)
    assert sum(b["samples"] for b in bands.values()) == 3


def test_empirical_rates_label_outcomes(config):
    # With the HR on 07-06, only the 07-03 sample (07-04..07-06 window) hits.
    bands = empirical_rates({"1": _history_player()}, config)
    assert sum(b["hr_followed"] for b in bands.values()) == 1
    for b in bands.values():
        assert b["rate"] == round(b["hr_followed"] / b["samples"], 3)


def test_empirical_rates_empty_store(config):
    assert empirical_rates({}, config) == {}


# ---- predictions + records -------------------------------------------------

def test_compute_predictions_ranks_and_excludes_stale(config):
    hot = {"player_name": "Hot Guy", "team": "NYY",
           "days": {"2026-07-02": day(near=2), "2026-07-03": day(near=2),
                    "2026-07-04": day(near=3, max_ev=110.0, parks=15)}}
    cold = {"player_name": "Cold Guy", "team": "BOS",
            "days": {"2026-07-04": day(near=0, parks=0, max_ev=82.0)}}
    stale = {"player_name": "Stale Guy", "team": "LAD",
             "days": {"2026-06-20": day(near=3)}}
    store = FakeStore({"1": hot, "2": cold, "3": stale})
    preds = compute_predictions(store, "2026-07-04", config)
    names = [p["player_name"] for p in preds["players"]]
    assert names[0] == "Hot Guy"
    assert "Stale Guy" not in names
    assert preds["players"][0]["streak"] == 3
    # Far below min_samples, the empirical % must stay hidden.
    assert preds["players"][0]["band_rate"] is None


def test_predictions_carry_informational_7d_fields(config):
    hot = {"player_name": "Hot Guy", "team": "NYY",
           "days": {"2026-07-03": day(near=2, xbh=1, hr=1, max_ev=104.0,
                                      dist=395.0),
                    "2026-07-04": day(near=3, xbh=2, hr=0, max_ev=110.0,
                                      dist=428.0)}}
    preds = compute_predictions(FakeStore({"1": hot}), "2026-07-04", config)
    p = preds["players"][0]
    assert p["hr_7d"] == 1
    assert p["near_hr_xbh_7d"] == 3
    assert p["max_ev_7d"] == 110.0
    assert p["max_distance_7d"] == 428


def test_predictions_rank_by_weather_adjusted_score(config):
    def player(team, name):
        return {"player_name": name, "team": team,
                "days": {"2026-07-02": day(near=2), "2026-07-03": day(near=2),
                         "2026-07-04": day(near=2)}}
    store = FakeStore({"1": player("NYY", "Wind Out Guy"),
                       "2": player("BOS", "Wind In Guy")})
    team_weather = {"NYY": wx(temp_f=90.0, wind_mph=12.0, wind_dir="out"),
                    "BOS": wx(temp_f=55.0, wind_mph=12.0, wind_dir="in")}
    preds = compute_predictions(store, "2026-07-04", config,
                                team_weather=team_weather)
    first, second = preds["players"]
    assert first["player_name"] == "Wind Out Guy"
    # Identical form: same base score and band; only the adjustment differs.
    assert first["expectancy_score"] == second["expectancy_score"]
    assert first["band"] == second["band"]
    assert first["weather_factor"] > 1.0 > second["weather_factor"]
    assert first["adjusted_score"] > second["adjusted_score"]
    assert first["game_weather"]["wind_dir"] == "out"
    assert second["game_weather"]["temp_f"] == 55.0


def test_predictions_neutral_without_weather_map(config):
    hot = {"player_name": "Hot Guy", "team": "NYY",
           "days": {"2026-07-03": day(near=2), "2026-07-04": day(near=2)}}
    preds = compute_predictions(FakeStore({"1": hot}), "2026-07-04", config)
    p = preds["players"][0]
    assert p["weather_factor"] == 1.0
    assert p["adjusted_score"] == p["expectancy_score"]
    assert p["game_weather"] is None


def test_predictions_neutral_for_team_not_playing(config):
    hot = {"player_name": "Hot Guy", "team": "NYY",
           "days": {"2026-07-03": day(near=2), "2026-07-04": day(near=2)}}
    preds = compute_predictions(FakeStore({"1": hot}), "2026-07-04", config,
                                team_weather={"BOS": wx(temp_f=95.0)})
    p = preds["players"][0]
    assert p["weather_factor"] == 1.0
    assert p["game_weather"] is None


def test_prediction_record_write_and_resolve(tmp_path, config):
    hot = {"player_name": "Hot Guy", "team": "NYY",
           "days": {"2026-07-02": day(near=2), "2026-07-03": day(near=2),
                    "2026-07-04": day(near=3, max_ev=110.0, parks=15)}}
    store = FakeStore({"1": hot})
    preds = compute_predictions(store, "2026-07-04", config)
    path = write_prediction_record(tmp_path / "predictions", preds, config)
    assert path.name == "2026-07-04.json"
    rec = json.loads(path.read_text())
    assert rec["players"][0]["player_id"] == 1

    # Not resolvable yet: no stored days beyond the record's horizon.
    assert resolve_prediction_records(tmp_path / "predictions",
                                      store.read_player_days(), config) is None

    # Player homers on 07-06 -> the 07-04 record resolves once data reaches 07-07.
    hot["days"]["2026-07-06"] = day(near=0, hr=1)
    hot["days"]["2026-07-07"] = day(near=0)
    result = resolve_prediction_records(tmp_path / "predictions",
                                        store.read_player_days(), config)
    assert result["resolved_records"] == 1
    assert result["overall"] == {"flagged": 1, "hr_followed": 1, "rate": 1.0}


def test_cross_check_reports_flagged_then_homered(tmp_path, config):
    hot = {"player_name": "Hot Guy", "team": "NYY",
           "days": {"2026-07-03": day(near=2), "2026-07-04": day(near=2)}}
    store = FakeStore({"1": hot})
    preds = compute_predictions(store, "2026-07-04", config)
    write_prediction_record(tmp_path / "p", preds, config)

    hot["days"]["2026-07-06"] = day(near=0, hr=2)
    hits = cross_check(tmp_path / "p", store.read_player_days(),
                       config, "2026-07-06")
    assert len(hits) == 1
    hit = hits[0]
    assert hit["player_name"] == "Hot Guy"
    assert hit["flagged_on"] == "2026-07-04"
    assert hit["hr_on"] == "2026-07-06"
    assert hit["hr_count"] == 2

    # Once the flag is older than the horizon it leaves the bucket
    # (it still counts in the aggregate track record).
    assert cross_check(tmp_path / "p", store.read_player_days(),
                       config, "2026-07-10") == []


def test_annotate_repeats_marks_returning_players(tmp_path, config):
    hot = {"player_name": "Hot Guy", "team": "NYY",
           "days": {"2026-07-03": day(near=2), "2026-07-04": day(near=2)}}
    store = FakeStore({"1": hot})
    preds = compute_predictions(store, "2026-07-04", config)
    write_prediction_record(tmp_path / "p", preds, config)

    hot["days"]["2026-07-05"] = day(near=2)
    new_guy = {"player_name": "New Guy", "team": "BOS",
               "days": {"2026-07-04": day(near=1), "2026-07-05": day(near=1)}}
    store = FakeStore({"1": hot, "2": new_guy})
    preds = annotate_repeats(compute_predictions(store, "2026-07-05", config),
                             tmp_path / "p")
    by_name = {p["player_name"]: p for p in preds["players"]}
    assert by_name["Hot Guy"]["repeat"] is True
    assert by_name["New Guy"]["repeat"] is False


def test_prediction_record_resolve_miss(tmp_path, config):
    hot = {"player_name": "Hot Guy", "team": "NYY",
           "days": {"2026-07-03": day(near=2), "2026-07-04": day(near=2)}}
    store = FakeStore({"1": hot})
    preds = compute_predictions(store, "2026-07-04", config)
    write_prediction_record(tmp_path / "predictions", preds, config)
    for d in ("2026-07-05", "2026-07-06", "2026-07-07"):
        hot["days"][d] = day(near=0)
    result = resolve_prediction_records(tmp_path / "predictions",
                                        store.read_player_days(), config)
    assert result["overall"] == {"flagged": 1, "hr_followed": 0, "rate": 0.0}


# ---- consistency leaderboard ------------------------------------------------

def test_consistency_leaderboard_ranks_by_consecutive_pulls(tmp_path, config):
    records = tmp_path / "records"
    # Hot Guy flagged on all three days; New Guy only on the latest.
    hot_days = {"2026-07-02": day(near=2), "2026-07-03": day(near=2),
                "2026-07-04": day(near=2)}
    for i, d in enumerate(["2026-07-02", "2026-07-03", "2026-07-04"]):
        days = {k: v for k, v in hot_days.items() if k <= d}
        players = {"1": {"player_name": "Hot Guy", "team": "NYY", "days": days}}
        if d == "2026-07-04":
            players["2"] = {"player_name": "New Guy", "team": "BOS",
                            "days": {"2026-07-04": day(near=2)}}
        store = FakeStore(players)
        preds = compute_predictions(store, d, config)
        write_prediction_record(records, preds, config)

    final_store = FakeStore({
        "1": {"player_name": "Hot Guy", "team": "NYY", "days": hot_days},
        "2": {"player_name": "New Guy", "team": "BOS",
              "days": {"2026-07-04": day(near=2)}},
    })
    board = consistency_leaderboard(records, final_store.read_player_days(),
                                    config, "2026-07-04")
    by_name = {p["player_name"]: p for p in board}
    assert by_name["Hot Guy"]["record_streak"] == 3
    assert by_name["Hot Guy"]["total_flags"] == 3
    assert by_name["New Guy"]["record_streak"] == 1
    assert board[0]["player_name"] == "Hot Guy"  # higher streak ranks first


def test_consistency_leaderboard_excludes_players_missing_latest_pull(tmp_path, config):
    records = tmp_path / "records"
    early = {"1": {"player_name": "Faded Guy", "team": "LAD",
                   "days": {"2026-07-01": day(near=2)}}}
    write_prediction_record(records,
                            compute_predictions(FakeStore(early), "2026-07-01", config),
                            config)
    # Faded Guy's last appearance is now 3 days stale (> max_gap_days=2), so he
    # no longer qualifies for the 07-04 record at all.
    later = {"1": {"player_name": "Faded Guy", "team": "LAD",
                   "days": {"2026-07-01": day(near=2)}},
             "2": {"player_name": "Fresh Guy", "team": "SEA",
                   "days": {"2026-07-04": day(near=2)}}}
    write_prediction_record(records,
                            compute_predictions(FakeStore(later), "2026-07-04", config),
                            config)
    board = consistency_leaderboard(records, FakeStore(later).read_player_days(),
                                    config, "2026-07-04")
    names = {p["player_name"] for p in board}
    assert "Fresh Guy" in names
    assert "Faded Guy" not in names  # not on the most recent record


def test_consistency_leaderboard_empty_when_no_records(tmp_path, config):
    assert consistency_leaderboard(tmp_path / "none", {}, config, "2026-07-04") == []
