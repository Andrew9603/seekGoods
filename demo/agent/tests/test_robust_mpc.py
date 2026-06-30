from __future__ import annotations

from agent.core.cargo_prior import CargoPrior
from agent.core.config import StrategyParams
from agent.core.constraint_automata import ConstraintAutomata
from agent.core.constraint_slack import ConstraintSlackEstimator
from agent.core.adaptive_mode import AdaptiveModeSelector
from agent.core.mpc_planner import MPCPlanner
from agent.core.penalty_calibrator import PenaltyCalibrator
from agent.core.region_value import RegionValueModel
from agent.core.scoring import ScoringEngine
from agent.tools.synthetic_driver_generator import generate_one

from .fake_simulation_api import FakeSimulationApi
from .test_agent_policy import cargo


def enriched(item: dict, finish: int = 12 * 60) -> dict:
    return {**item, "pickup_deadhead_km": 1.0, "linehaul_km": 20.0, "action_start_minute": 8 * 60, "estimated_finish_minute": finish}


def test_constraint_automata_compiles_all_constraint_families() -> None:
    prefs = {
        "hard_ban_categories": ["玻璃"],
        "soft_avoid_categories": ["冷链"],
        "scheduled_rest_windows": [{"start_minute": 0, "end_minute": 360}],
        "daily_rest": {"min_continuous_minutes": 360},
        "monthly_off_days": 2,
        "forbidden_regions": [{"region": "清远"}],
        "allowed_regions": ["广州"],
        "home_rules": [{"deadline_minute": 1320, "home_location": {"lat": 23.0, "lng": 113.7}}],
        "required_location_stops": [{"day": 10, "latitude": 23.1, "longitude": 113.8}],
        "max_pickup_deadhead_km": 40,
        "unknown_hard_constraints": ["必须按约定路线"],
    }
    kinds = {c.kind for c in ConstraintAutomata(prefs, StrategyParams()).constraints}
    assert {"category", "soft_preference", "time_window", "daily_rest", "monthly_off_day", "region_ban", "only_region", "home", "required_stop", "distance", "unknown_hard"} <= kinds


def test_constraint_automata_blocks_hard_category() -> None:
    automata = ConstraintAutomata({"hard_ban_categories": ["玻璃"]}, StrategyParams())
    result = automata.check_order(FakeSimulationApi().status, {}, enriched(cargo("x", name="玻璃")), 480, 720)
    assert result.allowed is False


def test_mpc_rejects_future_infeasible_required_stop_order() -> None:
    params = StrategyParams(enable_mpc_planner=True, deadline_safety_margin=180)
    item = enriched(cargo("far", end_lat=25.0, end_lng=116.0), finish=9 * 1440 + 10 * 60)
    scored = ScoringEngine(params, RegionValueModel()).score(
        FakeSimulationApi().status, [item], {"soft_avoid_categories": [], "required_region_order_days": []}, {}
    )
    prefs = {"required_location_stops": [{"day": 10, "latitude": 23.0, "longitude": 113.7, "deadline_minute_of_day": 12 * 60}]}
    action, debug = MPCPlanner(params, CargoPrior()).choose(FakeSimulationApi().status, prefs, {}, scored)
    assert action is None
    assert debug["mpc_evaluated"] == 0


def test_penalty_calibrator_hard_is_infinite_soft_is_tradeable() -> None:
    calibrator = PenaltyCalibrator(StrategyParams())
    assert calibrator.adjusted_penalty("category", 100, True) == float("inf")
    assert 0 < calibrator.adjusted_penalty("soft_category", 100, False) < float("inf")


def test_synthetic_generator_has_no_public_driver_templates() -> None:
    import random

    text = str(generate_one(random.Random(7), 1))
    assert "D001" not in text and "D002" not in text


def test_required_stop_slack_allows_room_and_detects_missed_deadline() -> None:
    estimator = ConstraintSlackEstimator(StrategyParams())
    prefs = {"required_location_stops": [{"day": 2, "latitude": 23.0, "longitude": 113.7, "deadline_minute_of_day": 12 * 60}]}
    status = {**FakeSimulationApi().status, "simulation_progress_minutes": 8 * 60}
    safe = estimator.estimate(status, prefs, history_summary={})
    missed = estimator.estimate(status, prefs, history_summary={}, current_time=2 * 1440)
    assert safe["required_stop_slack_minutes"] > 600
    assert missed["required_stop_slack_minutes"] < 0


def test_home_slack_detects_unreachable_order_endpoint() -> None:
    estimator = ConstraintSlackEstimator(StrategyParams())
    prefs = {"home_rules": [{"deadline_minute": 22 * 60, "home_location": {"lat": 23.0, "lng": 113.7}}]}
    status = {**FakeSimulationApi().status, "simulation_progress_minutes": 20 * 60}
    result = estimator.estimate(status, prefs, current_location=(25.0, 116.0))
    assert result["home_slack_minutes"] < 0


def test_daily_rest_negative_slack_is_blocked() -> None:
    estimator = ConstraintSlackEstimator(StrategyParams())
    prefs = {"daily_rest": {"min_continuous_minutes": 480}}
    status = {**FakeSimulationApi().status, "simulation_progress_minutes": 20 * 60}
    result = estimator.estimate(status, prefs, history_summary={"longest_wait_today": 0})
    assert result["daily_rest_slack_minutes"] < 0
    assert result["overall_slack_level"] == "blocked"


def test_adaptive_mode_query_pool_tracks_slack() -> None:
    selector = AdaptiveModeSelector()
    empty = {}
    assert selector.select({"overall_slack_level": "safe", "unknown_hard_risk": "none"}, empty) == "attack"
    assert selector.query_k("attack") == 300
    assert selector.select({"overall_slack_level": "blocked", "unknown_hard_risk": "none"}, empty) == "emergency"
    assert selector.query_k("emergency") == 30


def test_unknown_hard_risk_stays_guarded() -> None:
    selector = AdaptiveModeSelector()
    mode = selector.select({"overall_slack_level": "watch", "unknown_hard_risk": "high"}, {"unknown_hard_constraints": ["unknown"]})
    assert mode == "guard"
