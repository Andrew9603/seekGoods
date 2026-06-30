from __future__ import annotations

from typing import Any

from agent.core.cargo_filter import CargoFilter
from agent.core.config import StrategyParams
from agent.core.llm_helper import LLMHelper
from agent.core.preference_firewall import PreferenceFirewall
from agent.core.preference_parser import PreferenceParser
from agent.core.region_alias import coordinate_matches_region
from agent.model_decision_service import ModelDecisionService

from .fake_simulation_api import FakeSimulationApi
from .test_agent_policy import cargo


def parse_pref(text: str, *, robust: bool = True) -> dict[str, Any]:
    params = StrategyParams(
        enable_llm_preference_parser=False,
        hard_preference_filter_first=robust,
        strict_time_window_overlap_check=robust,
        strict_region_constraint=robust,
        strict_distance_limit=robust,
        unknown_preference_conservative=robust,
    )
    return PreferenceParser(LLMHelper(FakeSimulationApi(), params), params).parse("DHIDDEN", [{"content": text}])


def test_synthetic_hidden_preference_parser_cases() -> None:
    cases = [
        ("蔬菜几分钱一斤，凡是蔬菜货源我一律推掉，每接一次都扣钱。0点到6点睡觉，每天连续休息6小时。", lambda p: "蔬菜" in p["hard_ban_categories"] and p["scheduled_rest_windows"]),
        ("机械设备不接，接货空驶超过55公里不接。", lambda p: "机械设备" in p["hard_ban_categories"] and p["max_pickup_deadhead_km"] == 55),
        ("23点到次日6点不接单不空驶。", lambda p: {"start_minute": 23 * 60, "end_minute": 6 * 60} in p["scheduled_rest_windows"]),
        ("每月至少3天完整休息日，不出车不接单。", lambda p: p["monthly_off_days"] == 3),
        ("只在深圳跑，不能离开深圳。", lambda p: "深圳" in p.get("allowed_regions", [])),
        ("不去惠州，起点终点在惠州都不接。", lambda p: any(r.get("region") == "惠州" for r in p["forbidden_regions"])),
        ("装货地在广州不接。", lambda p: any(r.get("region") == "广州" for r in p["forbidden_regions"])),
        ("卸货地在佛山不接。", lambda p: any(r.get("region") == "佛山" for r in p["forbidden_regions"])),
        ("单笔装卸距离不超过150公里。", lambda p: p["max_haul_km"] == 150),
        ("每月接够4天增城相关订单。", lambda p: p["parser_confidence"] >= 0.9),
        ("每天23点前回家，次日8点前不再接单。", lambda p: p["requires_conservative_mode"]),
        ("3月10日10点前到23.15,113.67停留30分钟。", lambda p: p["required_location_stops"][0]["day"] == 10),
        ("先到A点接人，再回B点。", lambda p: p["requires_conservative_mode"]),
        ("中午12-13点不接单不空驶。", lambda p: {"start_minute": 12 * 60, "end_minute": 13 * 60} in p["scheduled_rest_windows"]),
        ("凌晨2-5点不跑车。", lambda p: {"start_minute": 2 * 60, "end_minute": 5 * 60} in p["scheduled_rest_windows"]),
        ("尽量不拉食品饮料。", lambda p: "食品饮料" in p["soft_avoid_categories"]),
        ("长途不接，短途优先。", lambda p: p["max_haul_km"] == 180.0),
        ("3月4号不进深圳。", lambda p: any(r.get("region") == "深圳" and r.get("days") == [4] for r in p["forbidden_regions"])),
        ("看到快递快运搬家都跳过。", lambda p: "快递快运搬家" in p["hard_ban_categories"]),
        ("这几天务必按我说的路线走，违背要扣罚。", lambda p: p["requires_conservative_mode"] and p["unknown_hard_constraints"]),
    ]
    for text, check in cases:
        parsed = parse_pref(text)
        assert check(parsed), text


def test_firewall_blocks_hard_category_and_region_alias() -> None:
    params = StrategyParams(hard_preference_filter_first=True, strict_region_constraint=True)
    firewall = PreferenceFirewall(params)
    status = FakeSimulationApi().status
    item = cargo("veg", name="新鲜蔬菜", end_lat=22.6, end_lng=113.9)
    prefs = parse_pref("不接蔬菜，不进深圳。")
    enriched = {**item, "pickup_deadhead_km": 1.0, "linehaul_km": 20.0}
    result = firewall.check_order(status, prefs, {}, enriched, 8 * 60, 10 * 60)
    assert result["allowed"] is False
    assert result["risk_level"] == "hard"


def test_firewall_cross_midnight_window_overlap() -> None:
    params = StrategyParams(strict_time_window_overlap_check=True)
    f = CargoFilter(params)
    item = cargo("late")
    item["cargo"]["load_time"] = ["2026-03-01 22:30:00", "2026-03-01 22:40:00"]
    item["cargo"]["cost_time_minutes"] = 90
    status = {**FakeSimulationApi().status, "simulation_progress_minutes": 22 * 60}
    prefs = parse_pref("23点到次日6点不接单不空驶。")
    assert f.filter_items(status, [item], prefs, {}) == []
    assert f.last_blocked


def test_firewall_blocks_order_crossing_into_date_region_ban() -> None:
    params = StrategyParams(strict_region_constraint=True)
    firewall = PreferenceFirewall(params)
    item = cargo("cross-day-region")
    item["cargo"]["end"] = {"city": "深圳"}
    enriched = {**item, "pickup_deadhead_km": 1.0, "linehaul_km": 20.0}
    preferences = {
        "hard_ban_categories": [],
        "soft_avoid_categories": [],
        "forbidden_regions": [{"region": "深圳", "days": [4]}],
    }
    result = firewall.check_order(
        FakeSimulationApi().status,
        preferences,
        {},
        enriched,
        3 * 1440 + 23 * 60,
        4 * 1440 + 2 * 60,
    )
    assert result["allowed"] is False
    assert "forbidden_region" in result["reasons"]


def test_firewall_blocks_coordinate_only_endpoint_in_date_region_ban() -> None:
    params = StrategyParams(strict_region_constraint=True)
    firewall = PreferenceFirewall(params)
    item = cargo("coordinate-only-region")
    item["cargo"]["end"] = {"city": "", "lat": 22.54, "lng": 114.06}
    enriched = {**item, "pickup_deadhead_km": 1.0, "linehaul_km": 20.0}
    preferences = {
        "hard_ban_categories": [],
        "soft_avoid_categories": [],
        "forbidden_regions": [{"region": "深圳", "days": [4]}],
    }
    result = firewall.check_order(
        FakeSimulationApi().status,
        preferences,
        {},
        enriched,
        3 * 1440 + 8 * 60,
        3 * 1440 + 12 * 60,
    )
    assert result["allowed"] is False


def test_firewall_allows_departure_from_forbidden_region_coordinate() -> None:
    params = StrategyParams(strict_region_constraint=True)
    firewall = PreferenceFirewall(params)
    status = {**FakeSimulationApi().status, "current_lat": 22.54, "current_lng": 114.06}
    item = cargo("leave-shenzhen")
    enriched = {**item, "pickup_deadhead_km": 1.0, "linehaul_km": 20.0}
    preferences = {
        "hard_ban_categories": [],
        "soft_avoid_categories": [],
        "forbidden_regions": [{"region": "深圳", "days": [4]}],
    }
    result = firewall.check_order(status, preferences, {}, enriched, 3 * 1440 + 8 * 60, 3 * 1440 + 12 * 60)
    assert result["allowed"] is True


def test_shenzhen_coordinate_is_not_misclassified_as_huizhou() -> None:
    assert coordinate_matches_region(22.54, 114.06, "深圳") is True
    assert coordinate_matches_region(22.54, 114.06, "惠州") is False


def test_unknown_hard_constraints_trigger_conservative_agent_action() -> None:
    params = StrategyParams(unknown_preference_conservative=True)
    parsed = parse_pref("这几天务必按我说的路线走，违背要扣罚。")
    assert parsed["requires_conservative_mode"] is True
    api = FakeSimulationApi(status={**FakeSimulationApi().status, "preferences": [{"content": "这几天务必按我说的路线走，违背要扣罚。"}]}, items=[cargo("1")])
    action = ModelDecisionService(api).decide("DHIDDEN")
    assert action["action"] in {"take_order", "reposition", "wait"}


def test_no_driver_id_special_case_in_hidden_parser() -> None:
    a = parse_pref("不接蔬菜。")
    b = PreferenceParser(LLMHelper(FakeSimulationApi(), StrategyParams(enable_llm_preference_parser=False)), StrategyParams(enable_llm_preference_parser=False)).parse("ANY_OTHER", [{"content": "不接蔬菜。"}])
    assert a["hard_ban_categories"] == b["hard_ban_categories"]


def test_llm_cannot_relax_rule_constraints() -> None:
    class UnsafeLlmApi(FakeSimulationApi):
        def model_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"max_pickup_deadhead_km":120,"monthly_off_days":1,'
                                '"requires_conservative_mode":false,"parser_confidence":1.0}'
                            )
                        }
                    }
                ]
            }

    params = StrategyParams(enable_llm_preference_parser=True, force_llm_when_preferences_exist=True)
    parsed = PreferenceParser(LLMHelper(UnsafeLlmApi(), params), params).parse(
        "DHIDDEN", [{"content": "接货空驶超过40公里不接，每月至少休息3个整天。"}]
    )
    assert parsed["max_pickup_deadhead_km"] == 40
    assert parsed["monthly_off_days"] == 3


def test_llm_schema_home_and_date_region_rules_are_normalized() -> None:
    class SchemaLlmApi(FakeSimulationApi):
        def model_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"home_rules":[{"deadline_time":"22:00","stay_until":"08:00",'
                                '"home_location":null}],'
                                '"date_region_bans":[{"date":"2026-03-15","region":"惠州"}],'
                                '"requires_conservative_mode":true,"parser_confidence":0.8}'
                            )
                        }
                    }
                ]
            }

    params = StrategyParams(enable_llm_preference_parser=True, force_llm_when_preferences_exist=True)
    parsed = PreferenceParser(LLMHelper(SchemaLlmApi(), params), params).parse(
        "DHIDDEN", [{"content": "每天晚上十点前回家，3月15日不能去惠州。"}]
    )
    assert parsed["home_rules"][0]["deadline_minute"] == 22 * 60
    assert any(rule.get("region") == "惠州" and 15 in rule.get("days", []) for rule in parsed["forbidden_regions"])
    assert parsed["requires_conservative_mode"] is True


def test_required_stop_does_not_borrow_neighbor_sentence_date() -> None:
    parsed = parse_pref("3月15日不能去惠州。3月20日上午10点前必须到23.21,113.37停留两小时。")
    stops = [stop for stop in parsed["required_location_stops"] if stop["latitude"] == 23.21]
    assert stops
    assert all(stop["day"] == 20 for stop in stops)
    assert all(stop["min_stop_minutes"] == 120 for stop in stops)


def test_home_rule_is_preserved_when_llm_omits_it() -> None:
    class OmittingLlmApi(FakeSimulationApi):
        def model_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"home_rules":[],"requires_conservative_mode":false,'
                                '"parser_confidence":1.0}'
                            )
                        }
                    }
                ]
            }

    params = StrategyParams(enable_llm_preference_parser=True, force_llm_when_preferences_exist=True)
    parsed = PreferenceParser(LLMHelper(OmittingLlmApi(), params), params).parse(
        "DHIDDEN", [{"content": "每天22点前必须回家，次日8点前不接单也不空驶。"}]
    )
    assert any(
        rule["deadline_minute"] == 22 * 60 and rule["stay_until_minute"] == 8 * 60
        for rule in parsed["home_rules"]
    )


def test_compact_chinese_date_region_ban_is_parsed() -> None:
    parsed = parse_pref("三月四号五号交警在深圳查车，这两天我不往深圳跑，也别给我派进去那边的货。")
    assert any(
        rule.get("region") == "深圳" and set(rule.get("days") or []) == {4, 5}
        for rule in parsed["forbidden_regions"]
    )
    assert not any(rule.get("region") == "深圳" and not rule.get("days") for rule in parsed["forbidden_regions"])


def test_llm_cannot_broaden_dated_region_ban_to_global() -> None:
    class BroadeningLlmApi(FakeSimulationApi):
        def model_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"forbidden_regions":["深圳"],"requires_conservative_mode":true,'
                                '"parser_confidence":0.8}'
                            )
                        }
                    }
                ]
            }

    params = StrategyParams(enable_llm_preference_parser=True, force_llm_when_preferences_exist=True)
    parsed = PreferenceParser(LLMHelper(BroadeningLlmApi(), params), params).parse(
        "DHIDDEN", [{"content": "三月四号五号不往深圳跑。"}]
    )
    assert any(rule.get("region") == "深圳" and set(rule.get("days") or []) == {4, 5} for rule in parsed["forbidden_regions"])
    assert not any(rule.get("region") == "深圳" and not rule.get("days") for rule in parsed["forbidden_regions"])
