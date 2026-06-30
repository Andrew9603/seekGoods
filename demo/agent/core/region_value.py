from __future__ import annotations

from typing import Any

from .geo import haversine_km
from .cargo_prior import CargoPrior


HOTSPOTS = [
    ("广州白云", 23.20, 113.27, 1.4),
    ("广州增城", 23.15, 113.67, 1.5),
    ("广州黄埔", 23.10, 113.48, 1.25),
    ("佛山南海", 23.04, 113.14, 1.15),
    ("佛山顺德", 22.84, 113.25, 1.12),
    ("东莞常平", 22.97, 114.00, 1.2),
    ("东莞大朗", 22.95, 113.94, 1.2),
    ("深圳龙岗", 22.72, 114.25, 1.15),
    ("深圳宝安", 22.60, 113.88, 1.1),
    ("惠州博罗", 23.17, 114.28, 0.8),
]


class RegionValueModel:
    def __init__(self, cargo_prior: CargoPrior | None = None) -> None:
        self._seen: dict[str, dict[str, dict[str, float]]] = {}
        self._cargo_prior = cargo_prior or CargoPrior()

    def observe_items(self, driver_id: str, items: list[dict[str, Any]]) -> None:
        driver_seen = self._seen.setdefault(str(driver_id), {})
        for item in items:
            cargo = item.get("cargo") if isinstance(item, dict) else None
            if not isinstance(cargo, dict):
                continue
            for endpoint in ("start", "end"):
                loc = cargo.get(endpoint) or {}
                key = self._grid(loc.get("lat"), loc.get("lng"))
                stat = driver_seen.setdefault(key, {"count": 0.0, "price": 0.0})
                stat["count"] += 1.0
                stat["price"] += float(cargo.get("price", 0) or 0)

    def destination_value(
        self, driver_id: str, lat: float, lng: float, preferences: dict[str, Any], city: str = ""
    ) -> float:
        value = self._cargo_prior.destination_value(city)
        for _, hlat, hlng, weight in HOTSPOTS:
            dist = haversine_km(lat, lng, hlat, hlng)
            value = max(value, weight * max(0.0, 1.0 - dist / 80.0))
        stat = self._seen.get(str(driver_id), {}).get(self._grid(lat, lng))
        if stat:
            value += min(1.0, stat["count"] / 20.0) + min(1.0, stat["price"] / max(stat["count"], 1.0) / 50000.0)
        for req in preferences.get("required_region_order_days") or []:
            region = req.get("region", "") if isinstance(req, dict) else ""
            if region and self._near_region_name(lat, lng, region):
                value += 1.5
        return value

    @staticmethod
    def _grid(lat: Any, lng: Any) -> str:
        try:
            return f"{round(float(lat), 1)},{round(float(lng), 1)}"
        except Exception:
            return "unknown"

    @staticmethod
    def _near_region_name(lat: float, lng: float, region: str) -> bool:
        for name, hlat, hlng, _ in HOTSPOTS:
            if region in name and haversine_km(lat, lng, hlat, hlng) <= 60:
                return True
        return False
