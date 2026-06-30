from __future__ import annotations

import concurrent.futures
import hashlib
import json
import time
from typing import Any

from simkit.ports import SimulationApiPort

from .config import StrategyParams


class LLMHelper:
    def __init__(self, api: SimulationApiPort, params: StrategyParams) -> None:
        self._api = api
        self._params = params
        self._cache: dict[str, dict[str, Any]] = {}
        self._failed_cache: set[str] = set()
        self._calls_by_driver: dict[str, int] = {}
        self._last: dict[str, Any] = {"llm_used": False, "llm_success": False, "llm_ms": 0, "llm_fallback_reason": ""}

    def last_debug(self) -> dict[str, Any]:
        return dict(self._last)

    def parse_preferences(self, driver_id: str, text: str) -> dict[str, Any] | None:
        self._last = {"llm_used": False, "llm_success": False, "llm_ms": 0, "llm_fallback_reason": ""}
        if not self._params.enable_llm_preference_parser or not text.strip():
            return None
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if key in self._cache:
            self._last = {"llm_used": False, "llm_success": True, "llm_ms": 0, "llm_fallback_reason": "cache_hit"}
            return dict(self._cache[key])
        if key in self._failed_cache:
            self._last = {"llm_used": False, "llm_success": False, "llm_ms": 0, "llm_fallback_reason": "cached_failure"}
            return None
        if self._calls_by_driver.get(driver_id, 0) >= self._params.llm_max_calls_per_driver:
            self._last["llm_fallback_reason"] = "driver_llm_budget_exhausted"
            return None

        prompt = text[:1600]
        payload = {
            "model": self._params.llm_preference_model_name,
            "max_completion_tokens": self._params.llm_preference_max_tokens,
            "thinking": {"type": "disabled"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a safety-critical freight-driver preference parser. Extract every explicit "
                        "and implied constraint from the Chinese text. Missing a hard constraint is much worse "
                        "than being conservative. Return exactly one JSON object, with no markdown or commentary. "
                        "Do not invent coordinates, dates, regions, or limits. Put a constraint into "
                        "unknown_hard_constraints only when it cannot be represented by any structured field. "
                        "Every unknown_hard_constraints item must be an exact, unchanged Chinese clause copied "
                        "from the user text; never add explanations, translations, enforcement notes, or repeat "
                        "a constraint already represented by a structured field. Set requires_conservative_mode=true "
                        "only when unknown_hard_constraints is non-empty. Preserve original "
                        "Chinese category and region words. Use this exact schema: "
                        '{"hard_ban_categories":[],"soft_avoid_categories":[],"daily_rest":'
                        '{"min_continuous_minutes":null,"preferred_windows":[]},'
                        '"forbidden_action_windows":[],"monthly_off_days":null,'
                        '"max_pickup_deadhead_km":null,"max_haul_km":null,"only_regions":[],'
                        '"forbidden_regions":[],"date_region_bans":[],"home_rules":[],'
                        '"required_stops":[],"required_region_order_days":[],'
                        '"unknown_hard_constraints":[],"unknown_soft_constraints":[],'
                        '"parser_confidence":0.0,"requires_conservative_mode":false}. '
                        "For windows use start/end HH:MM and booleans forbid_take_order, "
                        "forbid_reposition, forbid_driving. Bind dates, times, "
                        "regions, coordinates, stay durations, and sequence only to the same sentence or clause; "
                        "never copy a date or time from a neighboring sentence. For 'X before return home, next "
                        "day Y before no driving', home deadline_time is X and stay_until is Y. Convert Chinese "
                        "durations exactly: two hours is 120 minutes. A date-region ban must contain only the "
                        "date attached to that region ban. A required stop must use the date, deadline, coordinate, "
                        "duration, and sequence attached to that stop sentence. If any binding is uncertain, omit "
                        "the structured item, copy the full sentence into unknown_hard_constraints, and require "
                        "conservative mode."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        started = time.perf_counter()
        self._calls_by_driver[driver_id] = self._calls_by_driver.get(driver_id, 0) + 1
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self._api.model_chat_completion, payload)
                data = future.result(timeout=self._params.llm_parse_timeout_seconds)
            content = data["choices"][0]["message"]["content"]
            parsed = self._parse_json_object(content)
            if not isinstance(parsed, dict):
                raise ValueError("llm_json_not_object")
            self._cache[key] = parsed
            self._last = {
                "llm_used": True,
                "llm_success": True,
                "llm_ms": round((time.perf_counter() - started) * 1000, 2),
                "llm_fallback_reason": "",
            }
            return dict(parsed)
        except Exception as exc:
            self._failed_cache.add(key)
            self._last = {
                "llm_used": True,
                "llm_success": False,
                "llm_ms": round((time.perf_counter() - started) * 1000, 2),
                "llm_fallback_reason": f"{type(exc).__name__}: {exc}",
            }
            return None

    @staticmethod
    def _parse_json_object(content: Any) -> dict[str, Any]:
        if not isinstance(content, str):
            raise ValueError("llm_content_not_text")
        text = content.strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            object_start = text.find("{")
            if object_start < 0:
                raise ValueError("llm_json_object_not_found")
            parsed, _ = json.JSONDecoder().raw_decode(text[object_start:])
        if not isinstance(parsed, dict):
            raise ValueError("llm_json_not_object")
        return parsed
