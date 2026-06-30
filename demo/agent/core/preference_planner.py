from __future__ import annotations

from typing import Any

from .config import StrategyParams
from .geo import haversine_km, travel_minutes
from .time_utils import minute_of_day


class PreferencePlanner:
    def __init__(self, params: StrategyParams) -> None:
        self._params = params

    def plan(self, status: dict[str, Any], preferences: dict[str, Any], history: dict[str, Any]) -> dict[str, Any] | None:
        minute = int(status.get("simulation_progress_minutes", 0))
        monthly_need = preferences.get("monthly_off_days")
        if monthly_need and history.get("monthly_off_days_done", 0) < int(monthly_need):
            day = minute // 1440 + 1
            remaining_need = int(monthly_need) - int(history.get("monthly_off_days_done", 0))
            remaining_days = 31 - (day - 1)
            if day <= int(monthly_need) or remaining_days <= remaining_need:
                return {"action": "wait", "params": {"duration_minutes": max(1, 1440 - minute % 1440)}}
        stop_action = self._required_stop_action(status, preferences, history)
        if stop_action:
            return stop_action
        upcoming_rest = self._upcoming_rest_wait(minute, preferences)
        if upcoming_rest:
            return upcoming_rest
        rest_until = self.rest_window_end(minute, preferences)
        if rest_until:
            return {"action": "wait", "params": {"duration_minutes": max(1, min(rest_until, 12 * 60))}}
        return None

    def in_rest_window(self, minute: int, preferences: dict[str, Any]) -> bool:
        return self.rest_window_end(minute, preferences) is not None

    @staticmethod
    def rest_window_end(minute: int, preferences: dict[str, Any]) -> int | None:
        mod = minute_of_day(minute)
        for win in preferences.get("scheduled_rest_windows") or []:
            start = int(win.get("start_minute", 0))
            end = int(win.get("end_minute", 0))
            if start <= end:
                if start <= mod < end:
                    return end - mod
            elif mod >= start or mod < end:
                return (1440 - mod + end) if mod >= start else (end - mod)
        daily = (preferences.get("daily_rest") or {}).get("min_continuous_minutes")
        if daily and 0 <= mod < int(daily):
            return int(daily) - mod
        return None

    def _required_stop_action(self, status: dict[str, Any], preferences: dict[str, Any], history: dict[str, Any]) -> dict[str, Any] | None:
        minute = int(status.get("simulation_progress_minutes", 0))
        day = minute // 1440 + 1
        mod = minute_of_day(minute)
        lat, lng = float(status.get("current_lat", 0)), float(status.get("current_lng", 0))
        stops = sorted(
            preferences.get("required_location_stops") or [],
            key=lambda stop: (int(stop.get("day", 99)), int(stop.get("sequence", 2))),
        )
        for stop in stops:
            stop_day = int(stop.get("day", -1))
            if stop_day < day or stop_day > day + 1:
                continue
            target_lat = float(stop["latitude"])
            target_lng = float(stop["longitude"])
            target_grid = f"{round(target_lat, 2)},{round(target_lng, 2)}"
            stopped = target_grid in set((history.get("stopped_grids") or {}).get(stop_day - 1, []))
            if stopped:
                continue
            deadline = int(stop.get("deadline_minute_of_day", 18 * 60))
            distance = haversine_km(lat, lng, target_lat, target_lng)
            absolute_deadline = (stop_day - 1) * 1440 + deadline
            travel = travel_minutes(distance, self._params.reposition_speed_km_per_hour)
            if stop_day == day + 1:
                rest_reserve = self._max_rest_window_minutes(preferences)
                risk = preferences.get("_risk_level")
                safety_reserve = 8 * 60 if risk in {"structured_high_risk", "unknown_high_risk"} else 3 * 60
                if distance > 3 and absolute_deadline - minute <= travel + rest_reserve + safety_reserve:
                    return {"action": "reposition", "params": {"latitude": target_lat, "longitude": target_lng}}
                # Do not jump to a later same-day stop while this earlier sequence is pending.
                return None
            if distance > 3:
                if mod <= deadline:
                    return {"action": "reposition", "params": {"latitude": target_lat, "longitude": target_lng}}
            else:
                earliest = stop.get("earliest_minute_of_day")
                if earliest is not None and mod < int(earliest):
                    return {"action": "wait", "params": {"duration_minutes": int(earliest) + int(stop.get("min_stop_minutes", 120)) - mod}}
                return {"action": "wait", "params": {"duration_minutes": int(stop.get("min_stop_minutes", 120))}}
        return None

    @staticmethod
    def _max_rest_window_minutes(preferences: dict[str, Any]) -> int:
        reserve = int((preferences.get("daily_rest") or {}).get("min_continuous_minutes") or 0)
        for win in preferences.get("scheduled_rest_windows") or []:
            start = int(win.get("start_minute", 0))
            end = int(win.get("end_minute", 0))
            duration = end - start if end >= start else 1440 - start + end
            reserve = max(reserve, duration)
        return reserve

    def _upcoming_rest_wait(self, minute: int, preferences: dict[str, Any]) -> dict[str, Any] | None:
        mod = minute_of_day(minute)
        candidates: list[tuple[int, int]] = []
        for win in preferences.get("scheduled_rest_windows") or []:
            start = int(win.get("start_minute", 0))
            end = int(win.get("end_minute", 0))
            if mod < start:
                candidates.append((start - mod, end - mod if end >= start else 1440 - mod + end))
            elif start == 0 and mod >= 22 * 60:
                candidates.append((1440 - mod, 1440 - mod + end))
        daily = (preferences.get("daily_rest") or {}).get("min_continuous_minutes")
        if daily and mod >= 22 * 60:
            candidates.append((1440 - mod, 1440 - mod + int(daily)))
        if not candidates:
            return None
        until_start, duration = min(candidates, key=lambda x: x[0])
        if until_start <= 90:
            return {"action": "wait", "params": {"duration_minutes": max(1, duration)}}
        return None
