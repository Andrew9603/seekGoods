from __future__ import annotations

from typing import Any


class AdaptiveModeSelector:
    def select(self, slack: dict[str, Any], preferences: dict[str, Any]) -> str:
        level = slack.get("overall_slack_level", "safe")
        if level == "blocked":
            return "emergency"
        if level == "urgent" or slack.get("unknown_hard_risk") == "high":
            return "guard"
        if level == "watch":
            return "balanced"
        has_constraints = any(
            preferences.get(key)
            for key in (
                "required_location_stops",
                "home_rules",
                "scheduled_rest_windows",
                "monthly_off_days",
                "forbidden_regions",
                "allowed_regions",
                "only_regions",
            )
        ) or bool((preferences.get("daily_rest") or {}).get("min_continuous_minutes"))
        return "balanced" if has_constraints else "attack"

    @staticmethod
    def query_k(mode: str) -> int:
        return {"attack": 300, "balanced": 200, "guard": 100, "emergency": 30}.get(mode, 200)

    @staticmethod
    def soft_lambda(mode: str) -> float:
        return {"attack": 1.0, "balanced": 1.5, "guard": 2.5, "emergency": float("inf")}.get(mode, 1.5)
