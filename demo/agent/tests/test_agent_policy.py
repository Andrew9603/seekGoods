from __future__ import annotations

import builtins
import json

import pytest

from agent.core.config import StrategyParams, load_strategy_params
from agent.core.cargo_filter import CargoFilter
from agent.core.llm_helper import LLMHelper
from agent.core.preference_parser import PreferenceParser
from agent.core.preference_planner import PreferencePlanner
from agent.core.preference_firewall import PreferenceFirewall
from agent.core.region_value import RegionValueModel
from agent.core.scoring import ScoringEngine
from agent.model_decision_service import ModelDecisionService

from .fake_simulation_api import FakeSimulationApi


def cargo(cargo_id: str, name: str = "食品饮料", price: float = 10000.0, start_lat: float = 23.01, start_lng: float = 113.71, end_lat: float = 23.2, end_lng: float = 113.67) -> dict:
    return {
        "distance_km": 1.0,
        "cargo": {
            "cargo_id": cargo_id,
            "cargo_name": name,
            "price": price,
            "start": {"city": "广东省广州市增城区", "lat": start_lat, "lng": start_lng},
            "end": {"city": "广东省广州市白云区", "lat": end_lat, "lng": end_lng},
            "load_time": ["2026-03-01 08:00:00", "2026-03-01 10:00:00"],
            "cost_time_minutes": 60,
            "truck_length": ["4.2米"],
        },
    }


def test_decide_returns_valid_action() -> None:
    api = FakeSimulationApi(items=[cargo("1")])
    action = ModelDecisionService(api).decide("DTEST")
    assert action["action"] in {"take_order", "reposition", "wait"}
    assert isinstance(action["params"], dict)


def test_no_raw_data_file_read(monkeypatch: pytest.MonkeyPatch) -> None:
    real_open = builtins.open

    def guarded(path, *args, **kwargs):
        if "cargo_dataset.jsonl" in str(path) or "drivers.json" in str(path):
            raise AssertionError("raw data file read")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded)
    api = FakeSimulationApi(items=[cargo("1")])
    assert ModelDecisionService(api).decide("DTEST")["action"] in {"take_order", "reposition", "wait"}


def test_preference_parser_rule_based() -> None:
    api = FakeSimulationApi()
    parser = PreferenceParser(LLMHelper(api, StrategyParams(enable_llm_preference_parser=False)), StrategyParams(enable_llm_preference_parser=False))
    parsed = parser.parse(
        "D",
        [
            {"content": "蔬菜一律不接，每天至少连续休息8小时，0点到6点睡觉，三月得三个整天休息，接单后赶去装货空驶超过55公里不想接。"}
        ],
    )
    assert "蔬菜" in parsed["hard_ban_categories"]
    assert parsed["daily_rest"]["min_continuous_minutes"] == 480
    assert {"start_minute": 0, "end_minute": 360} in parsed["scheduled_rest_windows"]
    assert parsed["monthly_off_days"] == 3
    assert parsed["max_pickup_deadhead_km"] == 55


def test_llm_parser_timeout_fallback() -> None:
    api = FakeSimulationApi(llm_error=TimeoutError("slow"))
    api.status["preferences"] = [{"content": "坐标任务解析不了也不能失败"}]
    action = ModelDecisionService(api).decide("DTEST")
    assert action["action"] in {"take_order", "reposition", "wait"}


def test_llm_debug_success_flag() -> None:
    api = FakeSimulationApi()
    helper = LLMHelper(api, StrategyParams(enable_llm_preference_parser=True, llm_max_calls_per_driver=1))
    assert helper.parse_preferences("D", "some preference") == {}
    debug = helper.last_debug()
    assert debug["llm_used"] is True
    assert debug["llm_success"] is True


def test_strategy_profile_override(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    profiles = {
        "unit": {
            "overrides": {
                "query_k_peak": 321,
                "min_order_score": 12.5,
                "enable_llm_preference_parser": False,
            }
        }
    }
    profile_path = tmp_path / "profiles.json"
    profile_path.write_text(json.dumps(profiles), encoding="utf-8")
    monkeypatch.setenv("AGENT_STRATEGY_PROFILE", "unit")
    monkeypatch.setenv("AGENT_STRATEGY_PROFILES_PATH", str(profile_path))
    params = load_strategy_params()
    assert params.profile_name == "unit"
    assert params.query_k_peak == 321
    assert params.min_order_score == 12.5
    assert params.enable_llm_preference_parser is False


def test_forbidden_category_filter() -> None:
    f = CargoFilter(StrategyParams())
    result = f.filter_items(FakeSimulationApi().status, [cargo("1", name="蔬菜")], {"hard_ban_categories": ["蔬菜"], "forbidden_regions": []})
    assert result == []


def test_pickup_deadhead_limit_filter() -> None:
    item = cargo("1", start_lat=24.0, start_lng=114.8)
    item.pop("distance_km", None)
    result = CargoFilter(StrategyParams()).filter_items(FakeSimulationApi().status, [item], {"max_pickup_deadhead_km": 55, "hard_ban_categories": [], "forbidden_regions": []})
    assert result == []


def test_rest_window_priority() -> None:
    api = FakeSimulationApi(status={**FakeSimulationApi().status, "simulation_progress_minutes": 30, "preferences": [{"content": "0点到6点睡觉"}]}, items=[cargo("1")])
    action = ModelDecisionService(api).decide("DTEST")
    assert action["action"] == "wait"


def test_order_scoring_profit_per_hour() -> None:
    params = StrategyParams()
    engine = ScoringEngine(params, RegionValueModel())
    status = FakeSimulationApi().status
    fast = cargo("fast", price=8000)
    slow = cargo("slow", price=9000)
    slow["cargo"]["cost_time_minutes"] = 600
    items = CargoFilter(params).filter_items(status, [fast, slow], {"hard_ban_categories": [], "forbidden_regions": []})
    scored = engine.score(status, items, {"soft_avoid_categories": [], "required_region_order_days": []}, {})
    assert scored[0].cargo_id == "fast"


def test_fallback_on_query_cargo_exception() -> None:
    class BadApi(FakeSimulationApi):
        def query_cargo(self, driver_id: str, latitude: float, longitude: float, k: int = 100) -> dict:
            raise RuntimeError("boom")

    action = ModelDecisionService(BadApi()).decide("DTEST")
    assert action["action"] == "wait"


def test_required_stop_planner_prepositions_before_deadline_day() -> None:
    params = StrategyParams()
    planner = PreferencePlanner(params)
    status = {
        **FakeSimulationApi().status,
        "simulation_progress_minutes": 29 * 1440 + 18 * 60,
        "current_lat": 24.04,
        "current_lng": 115.70,
    }
    preferences = {
        "_risk_level": "structured_high_risk",
        "scheduled_rest_windows": [{"start_minute": 0, "end_minute": 360}],
        "required_location_stops": [
            {
                "day": 31,
                "latitude": 23.32,
                "longitude": 112.83,
                "deadline_minute_of_day": 12 * 60,
                "min_stop_minutes": 120,
            }
        ],
    }
    action = planner.plan(status, preferences, {})
    assert action == {"action": "reposition", "params": {"latitude": 23.32, "longitude": 112.83}}


def test_required_stop_planner_does_not_jump_to_later_sequence() -> None:
    planner = PreferencePlanner(StrategyParams())
    status = {
        **FakeSimulationApi().status,
        "simulation_progress_minutes": 29 * 1440 + 21 * 60,
        "current_lat": 23.18,
        "current_lng": 113.66,
    }
    preferences = {
        "_risk_level": "structured_high_risk",
        "scheduled_rest_windows": [{"start_minute": 0, "end_minute": 360}],
        "required_location_stops": [
            {
                "day": 31,
                "sequence": 1,
                "latitude": 23.15,
                "longitude": 113.67,
                "deadline_minute_of_day": 12 * 60,
                "min_stop_minutes": 1,
            },
            {
                "day": 31,
                "sequence": 2,
                "latitude": 23.32,
                "longitude": 112.83,
                "deadline_minute_of_day": 12 * 60,
                "min_stop_minutes": 120,
            },
        ],
    }
    assert planner.plan(status, preferences, {}) is None


def test_order_filter_preserves_required_stop_travel_reserve() -> None:
    params = StrategyParams()
    item = cargo("late", end_lat=24.04, end_lng=115.70)
    item["cargo"]["cost_time_minutes"] = 4 * 60
    status = {
        **FakeSimulationApi().status,
        "simulation_progress_minutes": 29 * 1440 + 18 * 60,
    }
    preferences = {
        "_risk_level": "structured_high_risk",
        "hard_ban_categories": [],
        "forbidden_regions": [],
        "required_location_stops": [
            {
                "day": 31,
                "latitude": 23.32,
                "longitude": 112.83,
                "deadline_minute_of_day": 12 * 60,
            }
        ],
    }
    result = CargoFilter(params).filter_items(status, [item], preferences)
    assert result == []


def test_forbidden_region_firewall_allows_exiting_current_region() -> None:
    params = StrategyParams(strict_region_constraint=True)
    status = {
        **FakeSimulationApi().status,
        "current_lat": 22.54,
        "current_lng": 114.47,
        "simulation_progress_minutes": 8 * 60,
    }
    preferences = {"forbidden_regions": [{"region": "深圳", "days": [1]}]}
    action = {"action": "reposition", "params": {"latitude": 23.15, "longitude": 113.67}}
    result = PreferenceFirewall(params).check_reposition(status, preferences, action)
    assert result["allowed"] is True


def test_home_rule_blocks_order_that_cannot_return_before_deadline() -> None:
    params = StrategyParams(strict_home_rule=True)
    firewall = PreferenceFirewall(params)
    item = cargo("late-home", end_lat=25.0, end_lng=116.0)
    enriched = {**item, "pickup_deadhead_km": 1.0, "linehaul_km": 20.0}
    preferences = {
        "home_rules": [
            {
                "deadline_minute": 22 * 60,
                "stay_until_minute": 8 * 60,
                "home_location": {"lat": 23.0, "lng": 113.7},
            }
        ]
    }
    result = firewall.check_order(
        FakeSimulationApi().status,
        preferences,
        {},
        enriched,
        18 * 60,
        21 * 60,
    )
    assert result["allowed"] is False
    assert "home_rule_deadline" in result["reasons"]


def test_unknown_high_risk_uses_short_order_limits() -> None:
    params = StrategyParams(
        max_order_duration_minutes_when_constraints_exist=600,
        max_order_duration_minutes_when_unknown_constraints_exist=300,
    )
    firewall = PreferenceFirewall(params)
    item = cargo("unknown-long")
    enriched = {**item, "pickup_deadhead_km": 1.0, "linehaul_km": 20.0}
    preferences = {
        "_raw_text_present": True,
        "_risk_level": "unknown_high_risk",
        "unknown_hard_constraints": ["必须按未知要求执行"],
    }
    result = firewall.check_order(FakeSimulationApi().status, preferences, {}, enriched, 8 * 60, 14 * 60)
    assert result["allowed"] is False


def test_structured_high_risk_allows_legal_medium_order() -> None:
    params = StrategyParams(max_order_duration_minutes_when_constraints_exist=600)
    firewall = PreferenceFirewall(params)
    item = cargo("known-medium")
    enriched = {**item, "pickup_deadhead_km": 1.0, "linehaul_km": 20.0}
    preferences = {
        "_raw_text_present": True,
        "_risk_level": "structured_high_risk",
        "required_location_stops": [{"day": 18, "latitude": 23.0, "longitude": 113.7}],
    }
    result = firewall.check_order(FakeSimulationApi().status, preferences, {}, enriched, 8 * 60, 14 * 60)
    assert result["allowed"] is True


def test_daily_rest_forces_wait_when_day_is_running_out() -> None:
    from agent.core.rest_planner import RestPlanner

    planner = RestPlanner(StrategyParams())
    status = {**FakeSimulationApi().status, "simulation_progress_minutes": 20 * 60}
    action = planner.plan(
        status,
        {"daily_rest": {"min_continuous_minutes": 480}},
        {"longest_wait_today": 0},
    )
    assert action == {"action": "wait", "params": {"duration_minutes": 480}}


def test_low_risk_keeps_peak_query_pool() -> None:
    service = ModelDecisionService(FakeSimulationApi())
    service._params = StrategyParams(query_k_peak=180)
    status = {**FakeSimulationApi().status, "simulation_progress_minutes": 10 * 60}
    assert service._choose_query_k(status, {"_risk_level": "no_pref_or_low_risk"}, {}) >= 180
