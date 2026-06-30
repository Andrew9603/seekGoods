from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CargoPrior:
    """Low-dimensional, static cargo-market aggregates."""

    def __init__(self, path: Path | None = None) -> None:
        path = path or Path(__file__).resolve().parents[1] / "config" / "cargo_prior.json"
        self._data: dict[str, Any] = {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = raw
        except Exception:
            self._data = {}

    def recommended_query_k(self, hour: int, default: int) -> int:
        value = (self._data.get("query_k_prior") or {}).get(str(int(hour) % 24))
        try:
            return max(1, int(value))
        except Exception:
            return int(default)

    def destination_value(self, city: str) -> float:
        stat = (self._data.get("destination_prior") or {}).get(str(city), {})
        try:
            return max(0.0, min(2.5, float(stat.get("opportunity_value", 0.0))))
        except Exception:
            return 0.0

    def score_bonus(self, hour: int, destination: str, category: str) -> float:
        hour_stat = (self._data.get("hour_prior") or {}).get(str(int(hour) % 24), {})
        dest_stat = (self._data.get("destination_prior") or {}).get(str(destination), {})
        category_stat = (self._data.get("category_prior") or {}).get(str(category), {})
        return (
            self._bounded(hour_stat.get("bonus"), 120.0)
            + self._bounded(dest_stat.get("bonus"), 180.0)
            + self._bounded(category_stat.get("bonus"), 120.0)
        )

    @staticmethod
    def _bounded(value: Any, maximum: float) -> float:
        try:
            return max(-maximum, min(maximum, float(value)))
        except Exception:
            return 0.0
