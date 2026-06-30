from __future__ import annotations

from typing import Any

from .config import StrategyParams
from .geo import haversine_km, travel_minutes
from .time_utils import minute_of_day


class HomeRulePlanner:
    def __init__(self, params: StrategyParams) -> None:
        self._params = params
        self._initial_locations: dict[str, tuple[float, float]] = {}

    def plan(self, driver_id: str, status: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any] | None:
        if not self._params.strict_home_rule or not preferences.get("home_rules"):
            return None
        lat, lng = float(status["current_lat"]), float(status["current_lng"])
        self._initial_locations.setdefault(driver_id, (lat, lng))
        self.attach_home_location(driver_id, status, preferences)
        now = int(status.get("simulation_progress_minutes", 0))
        mod = minute_of_day(now)
        rule = preferences["home_rules"][0]
        home = rule.get("home_location") if isinstance(rule, dict) else None
        home_lat, home_lng = float(home["lat"]), float(home["lng"])
        deadline = int(rule.get("deadline_minute", 22 * 60))
        stay_until = int(rule.get("stay_until_minute", 8 * 60))
        dist = haversine_km(lat, lng, home_lat, home_lng)
        travel = travel_minutes(dist, self._params.reposition_speed_km_per_hour)
        if mod >= deadline or mod < stay_until:
            if dist > 3:
                return {"action": "reposition", "params": {"latitude": home_lat, "longitude": home_lng}}
            wait = (stay_until - mod) if mod < stay_until else (1440 - mod + stay_until)
            return {"action": "wait", "params": {"duration_minutes": max(1, wait)}}
        if mod + travel + 180 >= deadline and dist > 3:
            return {"action": "reposition", "params": {"latitude": home_lat, "longitude": home_lng}}
        return None

    def attach_home_location(self, driver_id: str, status: dict[str, Any], preferences: dict[str, Any]) -> None:
        lat, lng = float(status["current_lat"]), float(status["current_lng"])
        self._initial_locations.setdefault(driver_id, (lat, lng))
        for rule in preferences.get("home_rules") or []:
            home = rule.get("home_location") if isinstance(rule, dict) else None
            if not isinstance(home, dict) or home.get("lat") is None or home.get("lng") is None:
                home_lat, home_lng = self._initial_locations[driver_id]
                rule["home_location"] = {"lat": home_lat, "lng": home_lng}
