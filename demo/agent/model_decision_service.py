"""Rule-first freight dispatch agent."""

from __future__ import annotations

import time
from typing import Any

from simkit.ports import SimulationApiPort

from agent.core.action_validator import validate_action
from agent.core.adaptive_mode import AdaptiveModeSelector
from agent.core.cargo_filter import CargoFilter
from agent.core.cargo_prior import CargoPrior
from agent.core.config import StrategyParams, load_strategy_params
from agent.core.constraint_slack import ConstraintSlackEstimator
from agent.core.history_analyzer import HistoryAnalyzer
from agent.core.home_rule_planner import HomeRulePlanner
from agent.core.llm_helper import LLMHelper
from agent.core.logger import AgentDebugLogger
from agent.core.mpc_planner import MPCPlanner
from agent.core.preference_parser import PreferenceParser
from agent.core.preference_firewall import PreferenceFirewall
from agent.core.preference_planner import PreferencePlanner
from agent.core.region_value import RegionValueModel
from agent.core.reposition_planner import RepositionPlanner
from agent.core.rest_planner import RestPlanner
from agent.core.risk_classifier import RiskClassifier
from agent.core.scoring import ScoringEngine


class ModelDecisionService:
    """Single-step decision service used by the benchmark harness."""

    def __init__(self, api: SimulationApiPort) -> None:
        self._api = api
        self._params: StrategyParams = load_strategy_params()
        self._llm = LLMHelper(api, self._params)
        self._parser = PreferenceParser(self._llm, self._params)
        self._history = HistoryAnalyzer()
        self._home_planner = HomeRulePlanner(self._params)
        self._cargo_prior = CargoPrior()
        self._region_value = RegionValueModel(self._cargo_prior)
        self._filter = CargoFilter(self._params)
        self._firewall = PreferenceFirewall(self._params)
        self._scoring = ScoringEngine(self._params, self._region_value, self._cargo_prior)
        self._pref_planner = PreferencePlanner(self._params)
        self._rest_planner = RestPlanner(self._params)
        self._reposition = RepositionPlanner(self._params, self._region_value)
        self._debug = AgentDebugLogger()
        self._risk_classifier = RiskClassifier()
        self._mpc = MPCPlanner(self._params, self._cargo_prior)
        self._slack = ConstraintSlackEstimator(self._params)
        self._adaptive = AdaptiveModeSelector()

    def decide(self, driver_id: str) -> dict[str, Any]:
        started = time.perf_counter()
        debug: dict[str, Any] = {"driver_id": driver_id, "fallback_reason": ""}
        allowed_ids: set[str] = set()
        status: dict[str, Any] = {}
        preferences: dict[str, Any] = {}
        try:
            status = self._api.get_driver_status(driver_id)
            debug["simulation_progress_minutes"] = status.get("simulation_progress_minutes")
            debug["location"] = [status.get("current_lat"), status.get("current_lng")]
            parse_started = time.perf_counter()
            preferences = self._parser.parse(driver_id, status.get("preferences", []))
            self._home_planner.attach_home_location(driver_id, status, preferences)
            risk_level = self._risk_classifier.classify(preferences)
            preferences["_risk_level"] = risk_level
            debug["risk_level"] = risk_level
            debug["structured_high_risk"] = risk_level == "structured_high_risk"
            debug["unknown_high_risk"] = risk_level == "unknown_high_risk"
            debug["active_hard_constraints"] = self._active_hard_constraints(preferences)
            debug["preference_parse_ms"] = round((time.perf_counter() - parse_started) * 1000, 2)
            debug["preference_parse_result"] = self._summarize_preferences(preferences)
            debug.update(self._llm.last_debug())

            history = self._history.analyze(
                self._api.query_decision_history(driver_id, 80),
                int(status.get("simulation_progress_minutes", 0)),
            )
            slack = self._slack.estimate(status, preferences, history_summary=history)
            adaptive_mode = self._adaptive.select(slack, preferences) if self._params.enable_adaptive_mode else "balanced"
            preferences["_adaptive_mode"] = adaptive_mode
            debug["constraint_slack"] = slack
            debug["adaptive_mode"] = adaptive_mode

            home_action = self._home_planner.plan(driver_id, status, preferences)
            if home_action:
                debug["home_rule_action"] = home_action
                return self._finish(driver_id, home_action, allowed_ids, status, preferences, debug, started)

            forced = self._pref_planner.plan(status, preferences, history)
            if forced:
                debug["selected_action"] = forced
                return self._finish(driver_id, forced, allowed_ids, status, preferences, debug, started)

            rest_action = self._rest_planner.plan(status, preferences, history)
            debug["rest_candidate"] = rest_action
            if rest_action:
                debug["selected_action"] = rest_action
                return self._finish(driver_id, rest_action, allowed_ids, status, preferences, debug, started)

            query_k = self._choose_query_k(status, preferences, history)
            debug["query_k"] = query_k
            cargo_resp = self._api.query_cargo(
                driver_id=driver_id,
                latitude=float(status["current_lat"]),
                longitude=float(status["current_lng"]),
                k=query_k,
            )
            items = cargo_resp.get("items") or []
            if not isinstance(items, list):
                items = []
            debug["cargo_count"] = len(items)
            debug["returned_count"] = len(items)
            debug["query_scan_cost_minutes"] = (len(items) + 9) // 10 if items else 0
            self._region_value.observe_items(driver_id, items)

            candidates = self._filter.filter_items(status, items, preferences, history)
            allowed_ids = {str(c["cargo"].get("cargo_id")) for c in candidates if isinstance(c.get("cargo"), dict)}
            scored = self._scoring.score(status, candidates, preferences, history)
            debug["filtered_count"] = max(0, len(items) - len(candidates))
            debug["firewall_blocked_count"] = len(self._filter.last_blocked)
            debug["firewall_blocked_sample"] = self._filter.last_blocked[:8]
            debug.update(self._blocked_diagnostics(self._filter.last_blocked))
            debug["allowed_long_order_count"] = sum(
                1 for item in candidates if int(item.get("estimated_finish_minute", 0)) - int(item.get("action_start_minute", 0)) > 300
            )
            debug["top_5_order_scores"] = [
                {
                    "cargo_id": s.cargo_id,
                    "score": round(s.score, 2),
                    "net_profit": round(s.net_profit, 2),
                    "preference_tradeoffs": s.preference_tradeoffs,
                }
                for s in scored[:5]
            ]

            min_order_score = self._params.min_order_score
            if self._params.enable_adaptive_mode and adaptive_mode == "attack":
                min_order_score = min(min_order_score, 10.0)
            elif self._params.enable_adaptive_mode and adaptive_mode == "guard":
                min_order_score = max(min_order_score, 80.0)
            elif self._params.enable_adaptive_mode and adaptive_mode == "emergency":
                min_order_score = float("inf")
            elif risk_level == "no_pref_or_low_risk":
                min_order_score = min(min_order_score, 30.0)
            elif risk_level == "unknown_high_risk":
                min_order_score = max(min_order_score, self._params.conservative_min_order_score)
            if preferences.get("unknown_hard_constraints") and self._params.unknown_preference_conservative:
                min_order_score = max(min_order_score, self._params.conservative_min_order_score)
                debug["conservative_mode"] = True
                debug["effective_min_order_score"] = min_order_score
            mpc_action = None
            if self._params.enable_mpc_planner and scored:
                mpc_action, mpc_debug = self._mpc.choose(status, preferences, history, scored)
                debug.update(mpc_debug)
            if mpc_action and scored and scored[0].score >= min_order_score:
                action = mpc_action
                selected = next((x for x in scored if x.cargo_id == action["params"]["cargo_id"]), scored[0])
                debug["selected_order_score"] = round(selected.score, 2)
                debug["expected_net_profit"] = round(selected.net_profit, 2)
                debug["selected_order_tradeoffs"] = selected.preference_tradeoffs
                debug["selected_order_duration"] = int(selected.item.get("estimated_finish_minute", 0)) - int(
                    selected.item.get("action_start_minute", 0)
                )
                debug["selected_order_finish_time"] = selected.item.get("estimated_finish_minute")
                debug["selected_order_finish_region"] = ((selected.item.get("cargo") or {}).get("end") or {}).get("city", "")
            elif scored and scored[0].score >= min_order_score and not self._params.enable_mpc_planner:
                action = {"action": "take_order", "params": {"cargo_id": scored[0].cargo_id}}
                debug["selected_order_score"] = round(scored[0].score, 2)
                debug["expected_net_profit"] = round(scored[0].net_profit, 2)
                debug["selected_order_tradeoffs"] = scored[0].preference_tradeoffs
                debug["selected_order_duration"] = int(scored[0].item.get("estimated_finish_minute", 0)) - int(
                    scored[0].item.get("action_start_minute", 0)
                )
                debug["selected_order_finish_time"] = scored[0].item.get("estimated_finish_minute")
                debug["selected_order_finish_region"] = ((scored[0].item.get("cargo") or {}).get("end") or {}).get("city", "")
            else:
                action = self._reposition.plan(status, preferences, history, scored)
                debug["reposition_candidate"] = action
                if not action:
                    action = self._rest_planner.low_value_wait(status)
            debug["selected_action"] = action
            return self._finish(driver_id, action, allowed_ids, status, preferences, debug, started)
        except Exception as exc:
            debug["fallback_reason"] = f"{type(exc).__name__}: {exc}"
            action = self._rest_planner.fallback_wait(status if status else None)
            return self._finish(driver_id, action, allowed_ids, status, preferences, debug, started)

    def _choose_query_k(self, status: dict[str, Any], preferences: dict[str, Any], history: dict[str, Any]) -> int:
        minute = int(status.get("simulation_progress_minutes", 0))
        hour = (minute // 60) % 24
        if self._pref_planner.in_rest_window(minute, preferences):
            return 1
        if self._params.enable_adaptive_mode:
            mode_k = self._adaptive.query_k(str(preferences.get("_adaptive_mode", "balanced")))
            if hour < 6 or hour >= 22:
                mode_k = min(mode_k, 120)
            return min(self._params.query_k_max, max(1, mode_k))
        risk_level = preferences.get("_risk_level", "structured_medium_risk")
        if risk_level == "unknown_high_risk":
            if hour < 6 or hour >= 22:
                return min(max(self._params.query_k_low, 80), 120)
            return min(max(self._params.query_k_default, 80), 120)
        prior_k = self._cargo_prior.recommended_query_k(hour, self._params.query_k_default)
        if hour < 6 or hour >= 22:
            return min(self._params.query_k_max, max(self._params.query_k_low, min(prior_k, 120)))
        if 8 <= hour <= 19:
            return min(self._params.query_k_max, max(self._params.query_k_peak, prior_k))
        if history.get("recent_empty_or_wait_steps", 0) >= 3:
            return min(self._params.query_k_max, max(prior_k, self._params.query_k_default + 50))
        return min(self._params.query_k_max, max(self._params.query_k_default, prior_k))

    def _finish(
        self,
        driver_id: str,
        action: dict[str, Any],
        allowed_ids: set[str],
        status: dict[str, Any],
        preferences: dict[str, Any],
        debug: dict[str, Any],
        started: float,
    ) -> dict[str, Any]:
        checked = validate_action(action, allowed_ids, status, preferences, self._params)
        if checked.get("action") == "reposition" and status:
            firewall = self._firewall.check_reposition(status, preferences, checked)
            debug["final_action_firewall"] = firewall
            if not firewall.get("allowed", False):
                checked = self._rest_planner.low_value_wait(status)
                debug["fallback_reason"] = debug.get("fallback_reason") or "reposition_firewall_fallback"
        if checked != action and not debug.get("fallback_reason"):
            debug["fallback_reason"] = "action_validator_fallback"
        debug["selected_action"] = checked
        debug["total_decision_ms"] = round((time.perf_counter() - started) * 1000, 2)
        self._debug.write(driver_id, debug)
        return checked

    @staticmethod
    def _summarize_preferences(preferences: dict[str, Any]) -> dict[str, Any]:
        return {
            "hard_ban_categories": preferences.get("hard_ban_categories", []),
            "soft_avoid_categories": preferences.get("soft_avoid_categories", []),
            "scheduled_rest_windows": preferences.get("scheduled_rest_windows", []),
            "monthly_off_days": preferences.get("monthly_off_days"),
            "max_pickup_deadhead_km": preferences.get("max_pickup_deadhead_km"),
            "max_haul_km": preferences.get("max_haul_km"),
            "parser_confidence": preferences.get("parser_confidence"),
            "unknown_hard_constraints": preferences.get("unknown_hard_constraints", []),
            "requires_conservative_mode": preferences.get("requires_conservative_mode", False),
            "home_rules": preferences.get("home_rules", []),
        }

    @staticmethod
    def _active_hard_constraints(preferences: dict[str, Any]) -> list[str]:
        mapping = {
            "home_rule": preferences.get("home_rules"),
            "required_stop": preferences.get("required_location_stops"),
            "date_region_ban": any(isinstance(x, dict) and x.get("days") for x in preferences.get("forbidden_regions") or []),
            "forbidden_window": preferences.get("scheduled_rest_windows"),
            "daily_rest": (preferences.get("daily_rest") or {}).get("min_continuous_minutes"),
            "monthly_off_days": preferences.get("monthly_off_days"),
            "distance_limit": preferences.get("max_pickup_deadhead_km") or preferences.get("max_haul_km"),
            "category_ban": preferences.get("hard_ban_categories"),
            "unknown_hard": preferences.get("unknown_hard_constraints"),
        }
        return [name for name, active in mapping.items() if active]

    @staticmethod
    def _blocked_diagnostics(blocked: list[dict[str, Any]]) -> dict[str, int]:
        reasons = [reason for item in blocked for reason in item.get("reasons", [])]
        return {
            "blocked_by_home_rule_count": sum("home_rule" in r for r in reasons),
            "blocked_by_required_stop_count": sum("required_stop" in r for r in reasons),
            "blocked_by_date_region_ban_count": sum("forbidden_region" in r for r in reasons),
            "blocked_by_forbidden_window_count": sum("blocked_time_window" in r for r in reasons),
            "blocked_by_daily_rest_count": sum("daily_rest" in r for r in reasons),
        }
