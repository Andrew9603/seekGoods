from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import StrategyParams
from .geo import haversine_km, travel_minutes
from .preference_firewall import PreferenceFirewall


@dataclass
class ConstraintResult:
    allowed: bool = True
    risk: float = 0.0
    penalty: float = 0.0
    reasons: list[str] = field(default_factory=list)


class Constraint:
    kind = "constraint"

    def __init__(self, value: Any, is_hard: bool = True) -> None:
        self.value = value
        self.is_hard = is_hard

    def check_action(self, state: dict[str, Any], action: dict[str, Any], interval: tuple[int, int]) -> ConstraintResult:
        return ConstraintResult()

    def update_after_action(self, state: dict[str, Any], action_result: dict[str, Any]) -> None:
        state["minute"] = int(action_result.get("simulation_progress_minutes", state.get("minute", 0)))

    def urgency_score(self, state: dict[str, Any]) -> float:
        return 0.0

    def future_feasibility(self, state: dict[str, Any], candidate_action: dict[str, Any]) -> bool:
        return True


class CategoryConstraint(Constraint): kind = "category"
class TimeWindowConstraint(Constraint): kind = "time_window"
class DailyRestConstraint(Constraint): kind = "daily_rest"
class MonthlyOffDayConstraint(Constraint): kind = "monthly_off_day"
class RegionBanConstraint(Constraint): kind = "region_ban"
class OnlyRegionConstraint(Constraint): kind = "only_region"
class HomeConstraint(Constraint): kind = "home"
class RequiredStopConstraint(Constraint): kind = "required_stop"
class DistanceConstraint(Constraint): kind = "distance"
class SoftPreferenceConstraint(Constraint): kind = "soft_preference"
class UnknownHardConstraint(Constraint): kind = "unknown_hard"


class ConstraintAutomata:
    def __init__(self, preferences: dict[str, Any], params: StrategyParams) -> None:
        self.preferences = preferences
        self.params = params
        self.firewall = PreferenceFirewall(params)
        self.constraints = self._compile(preferences)

    @staticmethod
    def _compile(p: dict[str, Any]) -> list[Constraint]:
        out: list[Constraint] = []
        mapping = [
            (CategoryConstraint, p.get("hard_ban_categories")),
            (TimeWindowConstraint, p.get("scheduled_rest_windows")),
            (DailyRestConstraint, (p.get("daily_rest") or {}).get("min_continuous_minutes")),
            (MonthlyOffDayConstraint, p.get("monthly_off_days")),
            (RegionBanConstraint, p.get("forbidden_regions")),
            (OnlyRegionConstraint, p.get("allowed_regions") or p.get("only_regions")),
            (HomeConstraint, p.get("home_rules")),
            (RequiredStopConstraint, p.get("required_location_stops")),
            (DistanceConstraint, [p.get("max_pickup_deadhead_km"), p.get("max_haul_km")]),
            (UnknownHardConstraint, p.get("unknown_hard_constraints")),
        ]
        for cls, value in mapping:
            if value and value != [None, None]:
                out.append(cls(value, True))
        if p.get("soft_avoid_categories") or p.get("avoid_regions"):
            out.append(SoftPreferenceConstraint([p.get("soft_avoid_categories"), p.get("avoid_regions")], False))
        return out

    def check_order(
        self, status: dict[str, Any], history: dict[str, Any], item: dict[str, Any], start: int, end: int
    ) -> ConstraintResult:
        result = self.firewall.check_order(status, self.preferences, history, item, start, end)
        return ConstraintResult(
            bool(result.get("allowed")),
            1.0 if result.get("risk_level") == "hard" else 0.2 if result.get("risk_level") == "soft" else 0.0,
            float(result.get("estimated_penalty") or 0.0),
            list(result.get("reasons") or []),
        )

    def future_feasibility(self, item: dict[str, Any], end_minute: int) -> bool:
        end = (item.get("cargo") or {}).get("end") or {}
        try:
            lat, lng = float(end["lat"]), float(end["lng"])
        except Exception:
            return False
        margin = int(self.params.deadline_safety_margin)
        for stop in self.preferences.get("required_location_stops") or []:
            try:
                deadline = (int(stop["day"]) - 1) * 1440 + int(stop.get("deadline_minute_of_day", 1080))
                if deadline >= end_minute:
                    travel = travel_minutes(haversine_km(lat, lng, float(stop["latitude"]), float(stop["longitude"])), self.params.reposition_speed_km_per_hour)
                    if end_minute + travel + margin > deadline:
                        return False
            except Exception:
                return False
        for rule in self.preferences.get("home_rules") or []:
            home = rule.get("home_location") or {}
            try:
                deadline = end_minute // 1440 * 1440 + int(rule.get("deadline_minute", 1320))
                travel = travel_minutes(haversine_km(lat, lng, float(home["lat"]), float(home["lng"])), self.params.reposition_speed_km_per_hour)
                if end_minute + travel + margin > deadline:
                    return False
            except Exception:
                return False
        return True

    def urgency_score(self, minute: int) -> float:
        urgency = 0.0
        for stop in self.preferences.get("required_location_stops") or []:
            deadline = (int(stop.get("day", 99)) - 1) * 1440 + int(stop.get("deadline_minute_of_day", 1080))
            remaining = deadline - minute
            if remaining > 0:
                urgency = max(urgency, max(0.0, 1.0 - remaining / 1440.0))
        return urgency
