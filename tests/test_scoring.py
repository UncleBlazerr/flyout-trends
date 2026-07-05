from hr_tracker.models import BattedBallEvent
from hr_tracker.scoring import barrel_score, score_event


def make_event(**kw) -> BattedBallEvent:
    base = dict(game_pk=1, date="2026-07-04", player_id=100, player_name="Test Batter",
                team="PIT", opponent="WSH", result="Flyout", exit_velocity=100.0,
                launch_angle=27.5, hit_distance=360.0, hc_x=100.0, hc_y=100.0,
                would_be_hr_count=0)
    base.update(kw)
    return BattedBallEvent(**base)


def test_distance_flag_set_for_deep_flyout(config):
    e = score_event(make_event(result="Flyout", hit_distance=380.0), config)
    assert e.distance_flag


def test_distance_flag_respects_threshold(config):
    e = score_event(make_event(hit_distance=349.0), config)
    assert not e.distance_flag


def test_distance_flag_excludes_home_runs(config):
    e = score_event(make_event(result="Home Run", hit_distance=420.0), config)
    assert not e.distance_flag


def test_distance_flag_handles_missing_distance(config):
    e = score_event(make_event(hit_distance=None), config)
    assert not e.distance_flag


def test_would_be_hr_flag_on_robbed_ball(config):
    min_parks = config["near_hr"]["would_be_hr"]["min_parks"]
    e = score_event(make_event(result="Lineout", would_be_hr_count=min_parks), config)
    assert e.would_be_hr_flag


def test_would_be_hr_flag_excludes_actual_hr(config):
    e = score_event(make_event(result="Home Run", would_be_hr_count=30), config)
    assert not e.would_be_hr_flag


def test_would_be_hr_flag_none_count(config):
    e = score_event(make_event(would_be_hr_count=None), config)
    assert not e.would_be_hr_flag


def test_barrel_score_bounds(config):
    weak = make_event(exit_velocity=60.0, launch_angle=-30.0, hit_distance=0.0)
    crushed = make_event(exit_velocity=115.0, launch_angle=27.5, hit_distance=450.0)
    assert barrel_score(weak, config["near_hr"]) == 0.0
    assert barrel_score(crushed, config["near_hr"]) == 100.0


def test_barrel_score_monotonic_in_ev(config):
    cfg = config["near_hr"]
    softer = barrel_score(make_event(exit_velocity=90.0), cfg)
    harder = barrel_score(make_event(exit_velocity=110.0), cfg)
    assert harder > softer


def test_barrel_flag_excludes_home_runs(config):
    e = score_event(make_event(result="Home Run", exit_velocity=115.0,
                               launch_angle=27.5, hit_distance=450.0), config)
    assert e.barrel_score == 100.0
    assert not e.barrel_flag


def test_is_near_hr_any_definition(config):
    e = score_event(make_event(result="Double", hit_distance=390.0,
                               would_be_hr_count=0, exit_velocity=80.0,
                               launch_angle=5.0), config)
    assert e.distance_flag and not e.would_be_hr_flag
    assert e.is_near_hr
