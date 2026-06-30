from __future__ import annotations

import math


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_km = 6371.0
    p1, l1, p2, l2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dp = p2 - p1
    dl = l2 - l1
    h = math.sin(dp * 0.5) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl * 0.5) ** 2
    return 2.0 * radius_km * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def travel_minutes(distance_km: float, speed_km_per_hour: float) -> int:
    if distance_km <= 1e-6:
        return 0
    return max(1, math.ceil(distance_km / max(speed_km_per_hour, 1e-6) * 60))
