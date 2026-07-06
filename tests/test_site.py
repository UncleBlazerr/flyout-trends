import json

from hr_tracker.scoring import score_events
from hr_tracker.site import build_site
from hr_tracker.store import FlatFileStore
from hr_tracker.trends import compute_trends

from test_store_trends import make_event


def test_build_site_writes_player_pages(tmp_path, config):
    store = FlatFileStore(tmp_path / "raw", tmp_path / "rollups")
    events = score_events(
        [make_event("2026-07-04", player_id=100),
         make_event("2026-07-04", player_id=200, name="Other Guy")], config)
    store.write_day("2026-07-04", events)

    cfg = {**config, "site": {**config["site"],
                              "output_dir": str(tmp_path / "docs")}}
    trends = compute_trends(store, "2026-07-04", cfg)
    build_site(events, trends, "2026-07-04", {}, cfg, store=store)

    docs = tmp_path / "docs"
    assert (docs / "player.html").exists()
    page = json.loads((docs / "data" / "players" / "100.json").read_text())
    assert page["player_name"] == "Test Batter"
    assert page["form"]["streak"] == 1
    assert len(page["events"]) == 1
    assert page["days"][0]["date"] == "2026-07-04"
    assert (docs / "data" / "players" / "200.json").exists()


def test_player_pages_span_trend_window_not_just_today(tmp_path, config):
    store = FlatFileStore(tmp_path / "raw", tmp_path / "rollups")
    for day in ("2026-07-01", "2026-07-04"):
        store.write_day(day, score_events([make_event(day)], config))
    today = score_events([make_event("2026-07-04")], config)

    cfg = {**config, "site": {**config["site"],
                              "output_dir": str(tmp_path / "docs")}}
    trends = compute_trends(store, "2026-07-04", cfg)
    build_site(today, trends, "2026-07-04", {}, cfg, store=store)

    page = json.loads(
        (tmp_path / "docs" / "data" / "players" / "100.json").read_text())
    assert [d["date"] for d in page["days"]] == ["2026-07-04", "2026-07-01"]
    assert len(page["events"]) == 2
