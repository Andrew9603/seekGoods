from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import StrategyParams
from .cargo_prior import CargoPrior
from .geo import travel_minutes
from .region_value import RegionValueModel
from .time_utils import wall_time_to_minute
from .adaptive_mode import AdaptiveModeSelector


@dataclass(frozen=True)
class ScoredOrder:
    cargo_id: str
    score: float
    net_profit: float
    profit_per_hour: float
    item: dict[str, Any]
    preference_tradeoffs: list[dict[str, Any]]


class ScoringEngine:
    def __init__(self, params: StrategyParams, region_value: RegionValueModel, cargo_prior: CargoPrior | None = None) -> None:
        self._params = params
        self._region_value = region_value
        self._cargo_prior = cargo_prior or CargoPrior()

    def score(self, status: dict[str, Any], items: list[dict[str, Any]], preferences: dict[str, Any], history: dict[str, Any]) -> list[ScoredOrder]:
        out = []
        self._active_risk_level = str(preferences.get("_risk_level", "structured_medium_risk"))
        self._active_adaptive_mode = str(preferences.get("_adaptive_mode", "balanced"))
        soft = set(preferences.get("soft_avoid_categories") or [])
        for item in items:
            cargo = item["cargo"]
            now = int(item.get("action_start_minute", status.get("simulation_progress_minutes", 0)))
            pickup_km = float(item.get("pickup_deadhead_km", 0))
            linehaul_km = float(item.get("linehaul_km", 0))
            price = self._price_yuan(cargo)
            cost_per_km = float(status.get("cost_per_km", self._params.cost_per_km_default) or self._params.cost_per_km_default)
            net_profit = price - cost_per_km * (pickup_km + linehaul_km)
            pickup_minutes = travel_minutes(pickup_km, self._params.reposition_speed_km_per_hour)
            wait_minutes = self._load_wait(now + pickup_minutes, cargo)
            total_minutes = pickup_minutes + wait_minutes + max(1, int(float(cargo.get("cost_time_minutes", 1))))
            profit_per_hour = net_profit / max(total_minutes / 60.0, 0.1)
            end = cargo.get("end") or {}
            remaining_days = max(0.0, (31 * 1440 - now) / 1440.0)
            is_endgame = remaining_days <= float(self._params.endgame_remaining_days)
            driver_id = str(status.get("driver_id", ""))
            dest_value = self._region_value.destination_value(
                driver_id, float(end["lat"]), float(end["lng"]), preferences, str(end.get("city", ""))
            )
            cargo_name = str(cargo.get("cargo_name", ""))
            prior_bonus = self._cargo_prior.score_bonus(
                (now // 60) % 24, str(end.get("city", "")), cargo_name
            )
            preference_penalty, tradeoffs = self._preference_penalty(cargo, preferences, net_profit, soft)
            req_bonus = self._required_region_bonus(cargo, preferences, history)
            rest_penalty = self._rest_crossing_penalty(now, int(item.get("estimated_finish_minute", now)), preferences)
            finish_bonus = self._finish_time_bonus(int(item.get("estimated_finish_minute", now)), preferences)
            destination_weight = self._params.destination_weight
            profit_per_hour_weight = self._params.profit_per_hour_weight
            pickup_penalty = self._params.pickup_deadhead_penalty
            long_order_penalty = 0.0
            risk_level = str(preferences.get("_risk_level", "structured_medium_risk"))
            if risk_level == "no_pref_or_low_risk":
                profit_per_hour_weight *= 1.2
                destination_weight *= 1.15
            elif risk_level == "unknown_high_risk":
                profit_per_hour_weight *= 0.85
            if is_endgame:
                destination_weight *= self._params.endgame_destination_weight_multiplier
                profit_per_hour_weight *= self._params.endgame_profit_per_hour_multiplier
                pickup_penalty *= self._params.endgame_pickup_penalty_multiplier
                long_order_penalty = self._params.endgame_long_order_penalty * max(0.0, total_minutes / 360.0 - 1.0)
            score = (
                self._params.profit_weight * net_profit
                + profit_per_hour_weight * profit_per_hour
                + destination_weight * dest_value
                + finish_bonus
                + prior_bonus
                + req_bonus
                - pickup_penalty * pickup_km
                - self._params.wait_minutes_penalty * wait_minutes
                - preference_penalty
                - rest_penalty
                - long_order_penalty
            )
            enriched = dict(item)
            enriched["expected_net_profit"] = round(net_profit, 2)
            enriched["finish_time_bonus"] = round(finish_bonus, 2)
            enriched["finish_location_value"] = round(dest_value, 4)
            enriched["cargo_prior_bonus"] = round(prior_bonus, 2)
            enriched["endgame_policy_active"] = is_endgame
            enriched["preference_tradeoffs"] = tradeoffs
            out.append(ScoredOrder(str(cargo["cargo_id"]), score, net_profit, profit_per_hour, enriched, tradeoffs))
        return sorted(out, key=lambda x: x.score, reverse=True)

    def _preference_penalty(
        self,
        cargo: dict[str, Any],
        preferences: dict[str, Any],
        expected_profit_gain: float,
        soft_categories: set[Any],
    ) -> tuple[float, list[dict[str, Any]]]:
        total = 0.0
        tradeoffs: list[dict[str, Any]] = []
        cargo_name = str(cargo.get("cargo_name", ""))
        for cat in soft_categories:
            if str(cat) and str(cat) in cargo_name:
                penalty = float(self._params.soft_category_penalty)
                decision = self._tradeoff_decision("soft_category", str(cat), penalty, expected_profit_gain)
                total += penalty if decision["tradeoff_decision"] == "accepted" else 1_000_000_000.0
                tradeoffs.append(decision)
        text = f"{((cargo.get('start') or {}).get('city') or '')} {((cargo.get('end') or {}).get('city') or '')}"
        for rule in preferences.get("avoid_regions") or []:
            region = rule.get("region") if isinstance(rule, dict) else str(rule)
            if region and str(region) in text:
                penalty = min(float(self._params.max_acceptable_preference_penalty_per_rule), 3000.0)
                decision = self._tradeoff_decision("avoid_region", str(region), penalty, expected_profit_gain)
                total += penalty if decision["tradeoff_decision"] == "accepted" else 1_000_000_000.0
                tradeoffs.append(decision)
        return total, tradeoffs

    def _tradeoff_decision(self, kind: str, value: str, expected_penalty: float, expected_profit_gain: float) -> dict[str, Any]:
        allowed = (
            self._params.allow_preference_tradeoff
            and kind in {"soft_category", "avoid_region"}
            and getattr(self, "_active_risk_level", "structured_medium_risk") != "unknown_high_risk"
            and expected_penalty <= float(self._params.max_acceptable_preference_penalty_per_rule)
            and expected_profit_gain
            > expected_penalty
            * (
                AdaptiveModeSelector.soft_lambda(getattr(self, "_active_adaptive_mode", "balanced"))
                if self._params.enable_adaptive_mode
                else float(self._params.penalty_safety_multiplier)
            )
        )
        return {
            "violated_preference_candidate": {"type": kind, "value": value},
            "expected_penalty": round(expected_penalty, 2),
            "expected_profit_gain": round(expected_profit_gain, 2),
            "tradeoff_decision": "accepted" if allowed else "rejected",
        }

    def _finish_time_bonus(self, finish_minute: int, preferences: dict[str, Any]) -> float:
        minute_of_day = finish_minute % 1440
        hour = minute_of_day // 60
        bonus = 0.0
        if 8 <= hour < 18:
            bonus += self._params.finish_daytime_bonus
        if 9 <= hour < 11 or 14 <= hour < 17:
            bonus += self._params.finish_peak_bonus
        if hour >= 22 or hour < 5:
            if preferences.get("scheduled_rest_windows") or (preferences.get("daily_rest") or {}).get("min_continuous_minutes"):
                bonus -= self._params.finish_late_rest_penalty
        return bonus

    @staticmethod
    def _price_yuan(cargo: dict[str, Any]) -> float:
        price = float(cargo.get("price", 0) or 0)
        return price / 100.0 if price > 1_000_000 else price

    @staticmethod
    def _load_wait(arrival: int, cargo: dict[str, Any]) -> int:
        load = cargo.get("load_time")
        if not isinstance(load, list) or len(load) != 2:
            return 0
        try:
            start = wall_time_to_minute(str(load[0]))
        except Exception:
            return 0
        return max(0, start - arrival)

    @staticmethod
    def _required_region_bonus(cargo: dict[str, Any], preferences: dict[str, Any], history: dict[str, Any]) -> float:
        text = f"{((cargo.get('start') or {}).get('city') or '')} {((cargo.get('end') or {}).get('city') or '')}"
        bonus = 0.0
        for rule in preferences.get("required_region_order_days") or []:
            region = rule.get("region", "") if isinstance(rule, dict) else ""
            min_days = int(rule.get("min_days", 0)) if isinstance(rule, dict) else 0
            done = int((history.get("region_days") or {}).get(region, 0))
            if region and region in text and done < min_days:
                bonus += 4000.0
        return bonus

    @staticmethod
    def _rest_crossing_penalty(start_minute: int, end_minute: int, preferences: dict[str, Any]) -> float:
        hits = 0
        for day in range(start_minute // 1440, end_minute // 1440 + 1):
            daily = (preferences.get("daily_rest") or {}).get("min_continuous_minutes")
            if daily and start_minute < day * 1440 + int(daily) and day * 1440 < end_minute:
                hits += 1
            for win in preferences.get("scheduled_rest_windows") or []:
                s = int(win.get("start_minute", 0))
                e = int(win.get("end_minute", 0))
                ws = day * 1440 + s
                we = day * 1440 + e if e >= s else (day + 1) * 1440 + e
                if start_minute < we and ws < end_minute:
                    hits += 1
        return hits * 1800.0
