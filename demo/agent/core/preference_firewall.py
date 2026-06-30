from __future__ import annotations

from typing import Any

from .config import StrategyParams
from .geo import haversine_km, travel_minutes
from .region_alias import cargo_matches_region, cargo_region_text, coordinate_matches_region, endpoint_matches_region
from .time_utils import minute_of_day


class PreferenceFirewall:
    def __init__(self, params: StrategyParams) -> None:
        self._params = params

    def check_order(
        self,
        status: dict[str, Any],
        preferences: dict[str, Any],
        history: dict[str, Any],
        item: dict[str, Any],
        start_minute: int,
        end_minute: int,
    ) -> dict[str, Any]:
        cargo = item.get("cargo") or {}
        reasons: list[str] = []
        soft_reasons: list[str] = []
        category = self._cargo_category(cargo)
        for banned in preferences.get("hard_ban_categories") or []:
            if str(banned) and str(banned) in category:
                reasons.append(f"hard_ban_category:{banned}")
        for soft in preferences.get("soft_avoid_categories") or []:
            if str(soft) and str(soft) in category:
                soft_reasons.append(f"soft_avoid_category:{soft}")
        if self._hits_forbidden_region(cargo, preferences, start_minute, end_minute):
            reasons.append("forbidden_region")
        if self._leaves_allowed_region(cargo, preferences):
            reasons.append("allowed_region_violation")
        if self._params.strict_distance_limit:
            max_pickup = preferences.get("max_pickup_deadhead_km")
            if max_pickup is not None and float(item.get("pickup_deadhead_km", 0.0)) > float(max_pickup):
                reasons.append("pickup_deadhead_limit")
            max_haul = preferences.get("max_haul_km")
            if max_haul is not None and float(item.get("linehaul_km", 0.0)) > float(max_haul):
                reasons.append("linehaul_limit")
        if self._params.strict_home_rule and self._misses_home_deadline(cargo, preferences, end_minute):
            reasons.append("home_rule_deadline")
        if self._has_preferences(preferences):
            duration = end_minute - start_minute
            high_unknown = preferences.get("_risk_level") == "unknown_high_risk"
            unknown_risk = bool(preferences.get("unknown_hard_constraints"))
            max_duration = (
                min(
                    self._params.max_order_duration_minutes_when_constraints_exist,
                    self._params.max_order_duration_minutes_when_unknown_constraints_exist,
                )
                if high_unknown and unknown_risk
                else self._params.max_order_duration_minutes_when_constraints_exist
            )
            max_pickup_safe = (
                min(
                    self._params.max_pickup_deadhead_km_when_constraints_exist,
                    self._params.max_pickup_deadhead_km_when_unknown_constraints_exist,
                )
                if high_unknown and unknown_risk
                else self._params.max_pickup_deadhead_km_when_constraints_exist
            )
            max_linehaul_safe = (
                min(
                    self._params.max_linehaul_km_when_constraints_exist,
                    self._params.max_linehaul_km_when_unknown_constraints_exist,
                )
                if high_unknown and unknown_risk
                else self._params.max_linehaul_km_when_constraints_exist
            )
            if duration > max_duration:
                reasons.append("submission_safe_order_duration_limit")
            if float(item.get("pickup_deadhead_km", 0.0)) > max_pickup_safe:
                reasons.append("submission_safe_pickup_limit")
            if float(item.get("linehaul_km", 0.0)) > max_linehaul_safe:
                reasons.append("submission_safe_linehaul_limit")
            if (high_unknown or self._params.avoid_cross_day_orders_if_preferences_exist) and start_minute // 1440 != end_minute // 1440:
                reasons.append("submission_safe_cross_day_order")
            start_hour = minute_of_day(start_minute) // 60
            if start_hour >= self._params.evening_cutoff_hour and duration > self._params.max_evening_order_duration_minutes:
                reasons.append("evening_order_duration_limit")
        if self._params.strict_time_window_overlap_check and self._crosses_blocked_window(start_minute, end_minute, preferences):
            reasons.append("blocked_time_window_overlap")
        if self._params.strict_required_stop and self._crosses_required_stop(start_minute, end_minute, preferences):
            reasons.append("required_stop_deadline_overlap")
        if self._params.avoid_cross_day_long_orders_when_constraints_exist and self._has_constraints(preferences):
            if start_minute // 1440 != end_minute // 1440:
                reasons.append("cross_day_order_under_constraints")
        if self._params.prefer_short_orders_when_constraints_exist and self._has_constraints(preferences):
            if float(item.get("linehaul_km", 0.0)) > self._params.conservative_max_haul_km:
                reasons.append("long_order_under_constraints")
        if self._params.prefer_short_orders_when_unknown_constraints_exist and preferences.get("unknown_hard_constraints"):
            if float(item.get("linehaul_km", 0.0)) > self._params.max_linehaul_km_when_unknown_constraints_exist:
                reasons.append("long_order_under_unknown_constraints")
        if (
            preferences.get("requires_conservative_mode")
            and preferences.get("unknown_hard_constraints")
            and self._params.unknown_preference_conservative
        ):
            if self._conservative_order_risk(status, item, start_minute, end_minute):
                reasons.append("unknown_preference_conservative_mode")
        if reasons:
            return self._result(False, "hard", reasons, None, 0.98)
        if soft_reasons:
            return self._result(True, "soft", soft_reasons, 500.0 * len(soft_reasons), 0.85)
        return self._result(True, "none", [], None, float(preferences.get("parser_confidence", 1.0) or 1.0))

    def check_reposition(
        self,
        status: dict[str, Any],
        preferences: dict[str, Any],
        action: dict[str, Any],
    ) -> dict[str, Any]:
        minute = int(status.get("simulation_progress_minutes", 0))
        params = action.get("params") or {}
        try:
            lat = float(params["latitude"])
            lng = float(params["longitude"])
            dist = haversine_km(float(status["current_lat"]), float(status["current_lng"]), lat, lng)
        except Exception:
            return self._result(False, "hard", ["invalid_reposition"], None, 1.0)
        end = minute + travel_minutes(dist, self._params.reposition_speed_km_per_hour)
        reasons = []
        required_target = self._matches_required_target(lat, lng, preferences)
        if self._params.strict_time_window_overlap_check and self._crosses_blocked_window(minute, end, preferences):
            reasons.append("blocked_time_window_overlap")
        if self._point_hits_forbidden_region(lat, lng, preferences, minute, end):
            reasons.append("reposition_forbidden_region")
        if (
            preferences.get("requires_conservative_mode")
            and preferences.get("unknown_hard_constraints")
            and dist > self._params.conservative_max_pickup_km
            and not required_target
        ):
            reasons.append("conservative_reposition_distance")
        return self._result(not reasons, "hard" if reasons else "none", reasons, None, 0.95)

    @staticmethod
    def _matches_required_target(lat: float, lng: float, preferences: dict[str, Any]) -> bool:
        for stop in preferences.get("required_location_stops") or []:
            try:
                if haversine_km(lat, lng, float(stop["latitude"]), float(stop["longitude"])) <= 3:
                    return True
            except Exception:
                continue
        return False

    def _misses_home_deadline(self, cargo: dict[str, Any], preferences: dict[str, Any], end_minute: int) -> bool:
        end = cargo.get("end") or {}
        try:
            end_lat, end_lng = float(end["lat"]), float(end["lng"])
        except Exception:
            return True
        for rule in preferences.get("home_rules") or []:
            home = rule.get("home_location") if isinstance(rule, dict) else None
            if not isinstance(home, dict) or home.get("lat") is None or home.get("lng") is None:
                return True
            deadline_mod = int(rule.get("deadline_minute", 22 * 60))
            day_start = end_minute // 1440 * 1440
            deadline = day_start + deadline_mod
            if end_minute % 1440 < int(rule.get("stay_until_minute", 8 * 60)):
                deadline -= 1440
            travel = travel_minutes(
                haversine_km(end_lat, end_lng, float(home["lat"]), float(home["lng"])),
                self._params.reposition_speed_km_per_hour,
            )
            if end_minute + travel + 120 > deadline:
                return True
        return False

    def _hits_forbidden_region(
        self,
        cargo: dict[str, Any],
        preferences: dict[str, Any],
        start_minute: int,
        end_minute: int,
    ) -> bool:
        interval_days = set(range(start_minute // 1440 + 1, end_minute // 1440 + 2))
        for rule in preferences.get("forbidden_regions") or []:
            region = rule.get("region") if isinstance(rule, dict) else str(rule)
            days = rule.get("days") if isinstance(rule, dict) else None
            if region and self._cargo_hits_region(cargo, str(region)) and (
                not days or interval_days.intersection(int(day) for day in days)
            ):
                return True
        return False

    @staticmethod
    def _cargo_hits_region(cargo: dict[str, Any], region: str) -> bool:
        if cargo_matches_region(cargo, region):
            return True
        for endpoint in ("start", "end"):
            loc = cargo.get(endpoint) or {}
            try:
                if coordinate_matches_region(float(loc["lat"]), float(loc["lng"]), region):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _point_hits_forbidden_region(
        latitude: float,
        longitude: float,
        preferences: dict[str, Any],
        start_minute: int,
        end_minute: int,
    ) -> bool:
        interval_days = set(range(start_minute // 1440 + 1, end_minute // 1440 + 2))
        for rule in preferences.get("forbidden_regions") or []:
            region = rule.get("region") if isinstance(rule, dict) else str(rule)
            days = rule.get("days") if isinstance(rule, dict) else None
            if region and coordinate_matches_region(latitude, longitude, str(region)) and (
                not days or interval_days.intersection(int(day) for day in days)
            ):
                return True
        return False

    def _leaves_allowed_region(self, cargo: dict[str, Any], preferences: dict[str, Any]) -> bool:
        allowed = preferences.get("allowed_regions") or []
        if not allowed:
            return False
        for region in allowed:
            if endpoint_matches_region(cargo, "start", str(region)) and endpoint_matches_region(cargo, "end", str(region)):
                return False
        return True

    def _crosses_blocked_window(self, start_minute: int, end_minute: int, preferences: dict[str, Any]) -> bool:
        for day in range(start_minute // 1440, end_minute // 1440 + 1):
            daily = (preferences.get("daily_rest") or {}).get("min_continuous_minutes")
            if daily and self._overlaps(start_minute, end_minute, day * 1440, day * 1440 + int(daily)):
                return True
            for win in preferences.get("scheduled_rest_windows") or []:
                s = int(win.get("start_minute", 0))
                e = int(win.get("end_minute", 0))
                if s <= e:
                    if self._overlaps(start_minute, end_minute, day * 1440 + s, day * 1440 + e):
                        return True
                else:
                    if self._overlaps(start_minute, end_minute, day * 1440 + s, (day + 1) * 1440 + e):
                        return True
        return False

    def _crosses_required_stop(self, start_minute: int, end_minute: int, preferences: dict[str, Any]) -> bool:
        for stop in preferences.get("required_location_stops") or []:
            day = int(stop.get("day", -1)) - 1
            if day < 0:
                continue
            deadline = day * 1440 + int(stop.get("deadline_minute_of_day", 18 * 60))
            if start_minute < deadline <= end_minute:
                return True
        return False

    def _conservative_order_risk(self, status: dict[str, Any], item: dict[str, Any], start_minute: int, end_minute: int) -> bool:
        if float(item.get("pickup_deadhead_km", 0.0)) > self._params.conservative_max_pickup_km:
            return True
        if float(item.get("linehaul_km", 0.0)) > self._params.conservative_max_haul_km:
            return True
        mod = minute_of_day(start_minute)
        if mod >= self._params.conservative_night_wait_start_minute or mod < 6 * 60:
            return True
        return start_minute // 1440 != end_minute // 1440

    @staticmethod
    def _cargo_category(cargo: dict[str, Any]) -> str:
        fields = ("cargo_name", "name", "category", "cargo_type", "goods_type", "goods_name", "description", "remark")
        return " ".join(str(cargo.get(key) or "") for key in fields) + " " + cargo_region_text(cargo)

    @staticmethod
    def _has_preferences(preferences: dict[str, Any]) -> bool:
        return bool(preferences.get("_raw_text_present") or PreferenceFirewall._has_constraints(preferences))

    @staticmethod
    def _has_constraints(preferences: dict[str, Any]) -> bool:
        return any(
            [
                preferences.get("hard_ban_categories"),
                preferences.get("forbidden_regions"),
                preferences.get("allowed_regions"),
                preferences.get("scheduled_rest_windows"),
                preferences.get("required_location_stops"),
                preferences.get("max_pickup_deadhead_km"),
                preferences.get("max_haul_km"),
                (preferences.get("daily_rest") or {}).get("min_continuous_minutes"),
            ]
        )

    @staticmethod
    def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
        return a_start < b_end and b_start < a_end

    @staticmethod
    def _result(allowed: bool, risk_level: str, reasons: list[str], estimated_penalty: float | None, confidence: float) -> dict[str, Any]:
        return {
            "allowed": allowed,
            "risk_level": risk_level,
            "reasons": reasons,
            "estimated_penalty": estimated_penalty,
            "confidence": confidence,
        }
