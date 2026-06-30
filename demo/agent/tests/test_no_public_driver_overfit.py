from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.core.config import StrategyParams, load_strategy_params
from agent.core.llm_helper import LLMHelper
from agent.core.preference_parser import PreferenceParser

from .fake_simulation_api import FakeSimulationApi


AGENT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_PATHS = [AGENT_ROOT / "core", AGENT_ROOT / "model_decision_service.py"]


def parse_without_llm(text: str) -> dict[str, Any]:
    params = StrategyParams(
        enable_llm_preference_parser=False,
        unknown_preference_conservative=True,
    )
    return PreferenceParser(LLMHelper(FakeSimulationApi(), params), params).parse(
        "NEW_DRIVER", [{"content": text}]
    )


def production_source() -> str:
    files: list[Path] = []
    for path in PRODUCTION_PATHS:
        files.extend(path.rglob("*.py") if path.is_dir() else [path])
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def test_production_has_no_public_driver_or_probe_special_cases() -> None:
    source = production_source()
    for marker in ("D001", "D002", "HIDDEN_PROBE"):
        assert marker not in source


def test_production_has_no_embedded_api_key() -> None:
    source = production_source()
    assert ("s" + "k-") not in source
    assert ("t" + "p-") not in source


def test_new_region_date_ban_generalizes() -> None:
    parsed = parse_without_llm("3月12日不能去清远。")
    assert any(
        rule.get("region") == "清远" and rule.get("days") == [12]
        for rule in parsed["forbidden_regions"]
    )


def test_new_categories_generalize() -> None:
    parsed = parse_without_llm("不接玻璃和冷链。")
    assert "玻璃" in parsed["hard_ban_categories"]
    assert "冷链" in parsed["hard_ban_categories"]


def test_explicit_coordinate_required_stop_is_exact() -> None:
    parsed = parse_without_llm("3月18日15点前到 22.98,113.12 停留90分钟。")
    stop = parsed["required_location_stops"][0]
    assert stop["day"] == 18
    assert stop["deadline_minute_of_day"] == 15 * 60
    assert stop["latitude"] == 22.98
    assert stop["longitude"] == 113.12
    assert stop["min_stop_minutes"] == 90


def test_explicit_coordinate_overrides_named_region_fallback() -> None:
    parsed = parse_without_llm("3月18日15点前到增城 22.98,113.12 停留90分钟。")
    assert parsed["required_location_stops"]
    assert all(
        stop["latitude"] == 22.98 and stop["longitude"] == 113.12
        for stop in parsed["required_location_stops"]
    )


def test_unlocated_named_required_stop_becomes_unknown_hard_constraint() -> None:
    parsed = parse_without_llm("3月18日15点前必须到清远停留90分钟。")
    assert parsed["required_location_stops"] == []
    assert parsed["unknown_hard_constraints"]
    assert parsed["requires_conservative_mode"] is True


def test_cross_sentence_date_does_not_bind_to_required_stop() -> None:
    parsed = parse_without_llm("3月12日不能去清远。3月18日15点前到 22.98,113.12 停留90分钟。")
    stops = parsed["required_location_stops"]
    assert stops
    assert all(stop["day"] == 18 for stop in stops)
    assert any(
        rule.get("region") == "清远" and rule.get("days") == [12]
        for rule in parsed["forbidden_regions"]
    )


def test_sequential_named_stop_precedes_explicit_coordinate_stop() -> None:
    parsed = parse_without_llm("3月18日先到增城，再到 22.98,113.12 停留90分钟。")
    stops = parsed["required_location_stops"]
    assert len(stops) >= 2
    assert stops[0]["region"] == "增城"
    assert stops[0]["sequence"] == 1
    assert any(stop["latitude"] == 22.98 and stop["longitude"] == 113.12 for stop in stops[1:])


def test_llm_merge_is_monotonic_safe() -> None:
    class RelaxingLlmApi(FakeSimulationApi):
        def model_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"max_pickup_deadhead_km":100,"monthly_off_days":1,'
                                '"daily_rest":{"min_continuous_minutes":120},'
                                '"requires_conservative_mode":false,"parser_confidence":1.0}'
                            )
                        }
                    }
                ]
            }

    params = StrategyParams(
        enable_llm_preference_parser=True,
        force_llm_when_preferences_exist=True,
        unknown_preference_conservative=True,
    )
    parsed = PreferenceParser(LLMHelper(RelaxingLlmApi(), params), params).parse(
        "NEW_DRIVER",
        [{"content": "接货空驶不能超过40公里，每月至少休息3个整天，每天连续休息8小时。务必遵守。"}],
    )
    assert parsed["max_pickup_deadhead_km"] == 40
    assert parsed["monthly_off_days"] == 3
    assert parsed["daily_rest"]["min_continuous_minutes"] == 8 * 60
    assert parsed["requires_conservative_mode"] is True


def test_default_profile_is_robust_mpc_adaptive() -> None:
    assert load_strategy_params().profile_name == "robust_mpc_adaptive"


def test_region_aliases_and_fallback_coordinates_do_nothing_without_preferences() -> None:
    parsed = parse_without_llm("")
    assert parsed["forbidden_regions"] == []
    assert parsed["allowed_regions"] == []
    assert parsed["required_location_stops"] == []
