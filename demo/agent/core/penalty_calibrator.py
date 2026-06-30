from __future__ import annotations

from typing import Any

from .config import StrategyParams


class PenaltyCalibrator:
    def __init__(self, params: StrategyParams) -> None:
        self._params = params

    def multiplier(self, kind: str, is_hard: bool) -> float:
        if is_hard:
            return float("inf")
        return {
            "soft_category": 1.0,
            "few_category": 1.8,
            "reluctant_category": 1.6,
            "avoid_region": 1.8,
            "unknown_hard": self._params.unknown_risk_lambda,
        }.get(kind, self._params.soft_preference_lambda)

    def adjusted_penalty(self, kind: str, estimated_penalty: Any, is_hard: bool) -> float:
        value = float(estimated_penalty or 0.0)
        multiplier = self.multiplier(kind, is_hard)
        return float("inf") if multiplier == float("inf") else value * multiplier
