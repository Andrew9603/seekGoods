from __future__ import annotations

from typing import Any

from .config import StrategyParams
from .geo import haversine_km, travel_minutes
from .preference_firewall import PreferenceFirewall
from .region_alias import cargo_matches_region, coordinate_matches_region
from .time_utils import wall_time_to_minute


class CargoFilter:
    def __init__(self, params: StrategyParams) -> None:
        self._params = params
        self._firewall = PreferenceFirewall(params)
        self.last_blocked: list[dict[str, Any]] = []

    def filter_items(self, status: dict[str, Any], items: list[dict[str, Any]], preferences: dict[str, Any], history: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        out = []
        self.last_blocked = []
        history = history or {}
        now = int(status.get("simulation_progress_minutes", 0)) + ((len(items) + 9) // 10 if items else 0)
        for item in items:
            cargo = item.get("cargo") if isinstance(item, dict) else None
            if not isinstance(cargo, dict) or not cargo.get("cargo_id"):
                continue
            if not self._truck_ok(status.get("truck_length"), cargo.get("truck_length")):
                continue
            if self._category_banned(cargo, preferences.get("hard_ban_categories") or []):
                continue
            if self._hits_region_rule(cargo, preferences.get("forbidden_regions") or [], now):
                continue
            pickup_km = self._pickup_km(status, cargo, item)
            max_pickup = preferences.get("max_pickup_deadhead_km")
            if max_pickup is not None and pickup_km > float(max_pickup):
                continue
            max_haul = preferences.get("max_haul_km")
            if max_haul is not None and self._linehaul_km(cargo) > float(max_haul):
                continue
            finish = self._estimate_finish(now, pickup_km, cargo)
            if finish is None or finish > 31 * 1440:
                continue
            if self.crosses_rest_window(now, finish, preferences):
                self.last_blocked.append(
                    {
                        "cargo_id": str(cargo.get("cargo_id")),
                        "allowed": False,
                        "risk_level": "hard",
                        "reasons": ["blocked_time_window_overlap"],
                        "estimated_penalty": None,
                        "confidence": 0.98,
                    }
                )
                continue
            if self._crosses_required_stop(now, finish, preferences):
                self.last_blocked.append(
                    {
                        "cargo_id": str(cargo.get("cargo_id")),
                        "allowed": False,
                        "risk_level": "hard",
                        "reasons": ["required_stop_deadline_overlap"],
                        "estimated_penalty": None,
                        "confidence": 0.98,
                    }
                )
                continue
            if not self._can_reach_required_stop_after_order(finish, cargo, preferences):
                self.last_blocked.append(
                    {
                        "cargo_id": str(cargo.get("cargo_id")),
                        "allowed": False,
                        "risk_level": "hard",
                        "reasons": ["required_stop_travel_reserve"],
                        "estimated_penalty": None,
                        "confidence": 0.98,
                    }
                )
                continue
            enriched = dict(
                item,
                action_start_minute=now,
                pickup_deadhead_km=pickup_km,
                linehaul_km=self._linehaul_km(cargo),
                estimated_finish_minute=finish,
            )
            firewall = self._firewall.check_order(status, preferences, history, enriched, now, finish)
            enriched["preference_firewall"] = firewall
            if not firewall.get("allowed", False):
                self.last_blocked.append({"cargo_id": str(cargo.get("cargo_id")), **firewall})
                continue
            out.append(enriched)
        return out

    def _estimate_finish(self, now: int, pickup_km: float, cargo: dict[str, Any]) -> int | None:
        arrival = now + travel_minutes(pickup_km, self._params.reposition_speed_km_per_hour)
        load = cargo.get("load_time")
        ready = arrival
        if isinstance(load, list) and len(load) == 2:
            try:
                start, end = wall_time_to_minute(str(load[0])), wall_time_to_minute(str(load[1]))
            except Exception:
                start, end = arrival, arrival
            if arrival > end:
                return None
            ready = max(arrival, start)
        return ready + max(0, int(float(cargo.get("cost_time_minutes", 0))))

    def _pickup_km(self, status: dict[str, Any], cargo: dict[str, Any], item: dict[str, Any]) -> float:
        if item.get("distance_km") is not None:
            return float(item["distance_km"])
        start = cargo.get("start") or {}
        return haversine_km(float(status["current_lat"]), float(status["current_lng"]), float(start["lat"]), float(start["lng"]))

    @staticmethod
    def _linehaul_km(cargo: dict[str, Any]) -> float:
        start, end = cargo.get("start") or {}, cargo.get("end") or {}
        return haversine_km(float(start["lat"]), float(start["lng"]), float(end["lat"]), float(end["lng"]))

    @staticmethod
    def _truck_ok(driver_len: Any, cargo_lens: Any) -> bool:
        if not cargo_lens:
            return True
        if isinstance(cargo_lens, list):
            return str(driver_len) in {str(x) for x in cargo_lens}
        return str(driver_len) == str(cargo_lens)

    @staticmethod
    def _category(cargo: dict[str, Any]) -> str:
        return str(cargo.get("cargo_name") or cargo.get("category") or "")

    def _category_banned(self, cargo: dict[str, Any], banned: list[Any]) -> bool:
        name = self._category(cargo)
        return any(str(cat) and str(cat) in name for cat in banned)

    def _hits_region_rule(self, cargo: dict[str, Any], rules: list[Any], now: int) -> bool:
        text = f"{((cargo.get('start') or {}).get('city') or '')} {((cargo.get('end') or {}).get('city') or '')}"
        day = now // 1440 + 1
        for rule in rules:
            region = rule.get("region") if isinstance(rule, dict) else str(rule)
            days = rule.get("days") if isinstance(rule, dict) else None
            if region and (
                str(region) in text
                or cargo_matches_region(cargo, str(region))
                or self._endpoint_coordinate_hits_region(cargo, str(region))
            ) and (not days or day in days):
                return True
        return False

    @staticmethod
    def _endpoint_coordinate_hits_region(cargo: dict[str, Any], region: str) -> bool:
        for endpoint in ("start", "end"):
            loc = cargo.get(endpoint) or {}
            try:
                if coordinate_matches_region(float(loc["lat"]), float(loc["lng"]), region):
                    return True
            except Exception:
                continue
        return False

    def crosses_rest_window(self, start_minute: int, end_minute: int, preferences: dict[str, Any]) -> bool:
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
            for stop in preferences.get("required_location_stops") or []:
                pass
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

    def _can_reach_required_stop_after_order(
        self, end_minute: int, cargo: dict[str, Any], preferences: dict[str, Any]
    ) -> bool:
        end = cargo.get("end") or {}
        try:
            end_lat, end_lng = float(end["lat"]), float(end["lng"])
        except Exception:
            return False
        for stop in preferences.get("required_location_stops") or []:
            try:
                deadline = (int(stop["day"]) - 1) * 1440 + int(
                    stop.get("deadline_minute_of_day", 18 * 60)
                )
                if deadline < end_minute:
                    continue
                distance = haversine_km(end_lat, end_lng, float(stop["latitude"]), float(stop["longitude"]))
            except Exception:
                return False
            travel = travel_minutes(distance, self._params.reposition_speed_km_per_hour)
            safety = 3 * 60 if preferences.get("_risk_level") in {"structured_high_risk", "unknown_high_risk"} else 60
            if end_minute + travel + safety > deadline:
                return False
        return True

    @staticmethod
    def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
        return a_start < b_end and b_start < a_end
