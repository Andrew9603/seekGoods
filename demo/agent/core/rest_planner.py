from __future__ import annotations

from typing import Any

from .config import StrategyParams


class RestPlanner:
    def __init__(self, params: StrategyParams) -> None:
        self._params = params

    def plan(self, status: dict[str, Any], preferences: dict[str, Any], history: dict[str, Any]) -> dict[str, Any] | None:
        minute = int(status.get("simulation_progress_minutes", 0))
        hour = (minute // 60) % 24
        required = ((preferences.get("daily_rest") or {}).get("min_continuous_minutes"))
        if required and history.get("longest_wait_today", 0) < int(required):
            remaining = max(1, int(required) - int(history.get("longest_wait_today", 0)))
            minute_of_day = minute % 1440
            if hour < 6 or hour >= 23 or 1440 - minute_of_day <= remaining + 120:
                return {"action": "wait", "params": {"duration_minutes": min(12 * 60, remaining)}}
        return None

    def low_value_wait(self, status: dict[str, Any] | None) -> dict[str, Any]:
        minute = int((status or {}).get("simulation_progress_minutes", 0))
        hour = (minute // 60) % 24
        if hour < 6:
            duration = min(self._params.fallback_wait_minutes, 6 * 60 - minute % 1440)
        else:
            duration = self._params.fallback_wait_minutes
        return {"action": "wait", "params": {"duration_minutes": max(1, int(duration))}}

    def fallback_wait(self, status: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.low_value_wait(status)
