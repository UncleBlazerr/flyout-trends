import json

from hr_tracker.models import BattedBallEvent
from hr_tracker.scoring import score_events
from hr_tracker.store import FlatFileStore
from hr_tracker.trends import _linear_slope, compute_trends


def make_event(date, player_id=100, name="Test Batter", **kw):
    base = dict(game_pk=1, date=date, player_id=player_id, player_name=name,
                team="PIT", opponent="WSH", result="Flyout", exit_velocity=101.0,
                launch_angle=26.0, hit_distance=372.0, hc_x=1.0, hc_y=1.0,
                would_be_hr_count=8)
    base.update(kw)
    return BattedBallEvent(**base)


def make_store(tmp_path):
    return FlatFileStore(tmp_path / "raw", tmp_path / "rollups")


def test_write_read_roundtrip(tmp_path, config):
    store = make_store(tmp_path)
    events = score_events([make_event("2026-07-04")], config)
    store.write_day("2026-07-04", events)
    assert store.read_day("2026-07-04") == events
    assert store.read_range("2026-07-01", "2026-07-04") == events


def test_write_day_is_immutable_across_dates(tmp_path, config):
    store = make_store(tmp_path)
    store.write_day("2026-07-03", score_events([make_event("2026-07-03")], config))
    before = (tmp_path / "raw" / "2026-07-03.json").read_text()
    store.write_day("2026-07-04", score_events([make_event("2026-07-04")], config))
    assert (tmp_path / "raw" / "2026-07-03.json").read_text() == before


def test_rewrite_same_day_replaces_rollup_not_duplicates(tmp_path, config):
    store = make_store(tmp_path)
    store.write_day("2026-07-04", score_events(
        [make_event("2026-07-04"), make_event("2026-07-04")], config))
    store.write_day("2026-07-04", score_events([make_event("2026-07-04")], config))
    index = json.loads((tmp_path / "rollups" / "player_index.json").read_text())
    assert index["players"]["100"]["days"]["2026-07-04"]["bbe"] == 1


def test_read_player_history_filters(tmp_path, config):
    store = make_store(tmp_path)
    store.write_day("2026-07-04", score_events(
        [make_event("2026-07-04", player_id=100),
         make_event("2026-07-04", player_id=200, name="Other Guy")], config))
    hist = store.read_player_history(100, days=7, end="2026-07-04")
    assert len(hist) == 1 and hist[0].player_id == 100


def test_schema_version_written(tmp_path, config):
    store = make_store(tmp_path)
    store.write_day("2026-07-04", [])
    payload = json.loads((tmp_path / "raw" / "2026-07-04.json").read_text())
    assert payload["schema_version"] == 1


def test_linear_slope():
    assert _linear_slope([0, 1, 2, 3]) == 1.0
    assert _linear_slope([3, 2, 1, 0]) == -1.0
    assert _linear_slope([2, 2, 2]) == 0.0
    assert _linear_slope([5]) == 0.0


def test_compute_trends_counts_and_heating_up(tmp_path, config):
    store = make_store(tmp_path)
    # Rising near-HR activity across the 7-day window for player 100
    for i, day in enumerate(["2026-06-29", "2026-07-01", "2026-07-03", "2026-07-04"]):
        events = [make_event(day, would_be_hr_count=4 + 4 * i)
                  for _ in range(1 + (i > 1))]
        store.write_day(day, score_events(events, config))

    trends = compute_trends(store, "2026-07-04", config)
    assert trends["as_of"] == "2026-07-04"
    player = next(p for p in trends["players"] if p["player_id"] == 100)

    w7 = player["windows"]["7"]
    assert w7["near_hr_any"] >= 3
    assert w7["trend_direction"] == "rising"
    assert player["heating_up"] is True

    w30 = player["windows"]["30"]
    assert w30["bbe"] == 6
    assert w30["max_ev_near_hr"] == 101.0


def test_compute_trends_hr_not_near_hr(tmp_path, config):
    store = make_store(tmp_path)
    store.write_day("2026-07-04", score_events(
        [make_event("2026-07-04", result="Home Run", would_be_hr_count=30)], config))
    trends = compute_trends(store, "2026-07-04", config)
    w7 = trends["players"][0]["windows"]["7"]
    assert w7["hr"] == 1
    assert w7["near_hr_any"] == 0
    assert w7["would_be_hr_parks_sum"] == 0
