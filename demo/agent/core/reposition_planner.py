from __future__ import annotations

from typing import Any

from .config import StrategyParams
from .geo import haversine_km
from .region_value import HOTSPOTS, RegionValueModel


class RepositionPlanner:
    def __init__(self, params: StrategyParams, region_value: RegionValueModel) -> None:
        self._params = params
        self._region_value = region_value

    def plan(self, status: dict[str, Any], preferences: dict[str, Any], history: dict[str, Any], scored_orders: list[Any]) -> dict[str, Any] | None:
        if history.get("last_action") == "reposition":
            return None
        lat, lng = float(status["current_lat"]), float(status["current_lng"])
        forbidden = preferences.get("forbidden_regions") or []
        best = None
        best_value = 0.0
        for name, hlat, hlng, weight in HOTSPOTS:
            if any((r.get("region") if isinstance(r, dict) else str(r)) in name for r in forbidden):
                continue
            dist = haversine_km(lat, lng, hlat, hlng)
            if dist > self._params.max_reposition_km or dist < 5:
                continue
            value = weight * 100.0 - dist
            if value > best_value:
                best_value = value
                best = (hlat, hlng)
        if best and best_value >= self._params.reposition_score_threshold:
            return {"action": "reposition", "params": {"latitude": best[0], "longitude": best[1]}}
        return None
