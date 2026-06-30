from __future__ import annotations

from typing import Any

from .config import StrategyParams
from .geo import haversine_km, travel_minutes
from .region_alias import coordinate_matches_region


class ConstraintSlackEstimator:
    def __init__(self, params: StrategyParams) -> None:
        self.params = params

    def estimate(
        self,
        current_state: dict[str, Any],
        preferences: dict[str, Any],
        automata_state: Any = None,
        history_summary: dict[str, Any] | None = None,
        current_time: int | None = None,
        current_location: tuple[float, float] | None = None,
    ) -> dict[str, Any]:
        history = history_summary or {}
        minute = int(current_time if current_time is not None else current_state.get("simulation_progress_minutes", 0))
        lat, lng = current_location or (
            float(current_state.get("current_lat", 0.0)),
            float(current_state.get("current_lng", 0.0)),
        )
        required_slack = self._required_stop_slack(minute, lat, lng, preferences, history)
        home_slack = self._home_slack(minute, lat, lng, preferences)
        daily_slack = self._daily_rest_slack(minute, preferences, history)
        monthly_slack = self._monthly_off_slack(minute, preferences, history)
        date_risk = self._date_region_risk(minute, lat, lng, preferences)
        unknown_risk = "high" if preferences.get("unknown_hard_constraints") else "none"
        values = [x for x in (required_slack, home_slack, daily_slack) if x is not None]
        blocked = any(x < 0 for x in values) or (monthly_slack is not None and monthly_slack < 0) or date_risk == "active"
        urgent = any(x <= 180 for x in values) or (monthly_slack is not None and monthly_slack == 0)
        watch = any(x <= 480 for x in values) or date_risk in {"future", "imminent"} or unknown_risk == "high"
        level = "blocked" if blocked else "urgent" if urgent else "watch" if watch else "safe"
        reasons = []
        for name, value in (
            ("required_stop", required_slack),
            ("home", home_slack),
            ("daily_rest", daily_slack),
            ("monthly_off_day", monthly_slack),
        ):
            if value is not None and value <= (0 if name == "monthly_off_day" else 180):
                reasons.append(f"{name}_slack:{value}")
        if date_risk != "none":
            reasons.append(f"date_region_ban:{date_risk}")
        if unknown_risk == "high":
            reasons.append("unknown_hard_risk:high")
        return {
            "required_stop_slack_minutes": required_slack,
            "home_slack_minutes": home_slack,
            "daily_rest_slack_minutes": daily_slack,
            "monthly_off_day_slack_days": monthly_slack,
            "date_region_ban_risk": date_risk,
            "unknown_hard_risk": unknown_risk,
            "overall_slack_level": level,
            "reasons": reasons,
        }

    def estimate_after_order(
        self,
        status: dict[str, Any],
        preferences: dict[str, Any],
        history: dict[str, Any],
        item: dict[str, Any],
    ) -> dict[str, Any]:
        end = (item.get("cargo") or {}).get("end") or {}
        return self.estimate(
            status,
            preferences,
            history_summary=history,
            current_time=int(item.get("estimated_finish_minute", status.get("simulation_progress_minutes", 0))),
            current_location=(float(end["lat"]), float(end["lng"])),
        )

    def _required_stop_slack(
        self, minute: int, lat: float, lng: float, preferences: dict[str, Any], history: dict[str, Any]
    ) -> int | None:
        stopped = history.get("stopped_grids") or {}
        for stop in sorted(
            preferences.get("required_location_stops") or [],
            key=lambda x: (int(x.get("day", 99)), int(x.get("sequence", 2))),
        ):
            day_index = int(stop.get("day", 99)) - 1
            grid = f"{round(float(stop['latitude']), 2)},{round(float(stop['longitude']), 2)}"
            if grid in set(stopped.get(day_index, [])):
                continue
            deadline = day_index * 1440 + int(stop.get("deadline_minute_of_day", 1080))
            travel = travel_minutes(
                haversine_km(lat, lng, float(stop["latitude"]), float(stop["longitude"])),
                self.params.reposition_speed_km_per_hour,
            )
            return deadline - minute - travel
        return None

    def _home_slack(self, minute: int, lat: float, lng: float, preferences: dict[str, Any]) -> int | None:
        rules = preferences.get("home_rules") or []
        if not rules:
            return None
        rule = rules[0]
        home = rule.get("home_location") or {}
        try:
            travel = travel_minutes(
                haversine_km(lat, lng, float(home["lat"]), float(home["lng"])),
                self.params.reposition_speed_km_per_hour,
            )
        except Exception:
            return -1
        deadline = minute // 1440 * 1440 + int(rule.get("deadline_minute", 1320))
        if deadline < minute:
            deadline += 1440
        return deadline - minute - travel

    @staticmethod
    def _daily_rest_slack(minute: int, preferences: dict[str, Any], history: dict[str, Any]) -> int | None:
        required = int((preferences.get("daily_rest") or {}).get("min_continuous_minutes") or 0)
        if not required:
            return None
        still_needed = max(0, required - int(history.get("longest_wait_today", 0)))
        return 1440 - minute % 1440 - still_needed

    @staticmethod
    def _monthly_off_slack(minute: int, preferences: dict[str, Any], history: dict[str, Any]) -> int | None:
        required = int(preferences.get("monthly_off_days") or 0)
        if not required:
            return None
        remaining_days = max(0, 31 - minute // 1440)
        still_needed = max(0, required - int(history.get("monthly_off_days_done", 0)))
        return remaining_days - still_needed

    @staticmethod
    def _date_region_risk(minute: int, lat: float, lng: float, preferences: dict[str, Any]) -> str:
        day = minute // 1440 + 1
        nearest = 99
        for rule in preferences.get("forbidden_regions") or []:
            if not isinstance(rule, dict) or not rule.get("days"):
                continue
            region = str(rule.get("region") or "")
            days = [int(x) for x in rule.get("days") or []]
            if day in days and region and coordinate_matches_region(lat, lng, region):
                return "active"
            future = [x - day for x in days if x >= day]
            if future:
                nearest = min(nearest, min(future))
        return "imminent" if nearest <= 1 else "future" if nearest <= 3 else "none"
