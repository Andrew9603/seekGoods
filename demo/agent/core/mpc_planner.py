from __future__ import annotations

from typing import Any

from .cargo_prior import CargoPrior
from .config import StrategyParams
from .constraint_automata import ConstraintAutomata
from .penalty_calibrator import PenaltyCalibrator
from .constraint_slack import ConstraintSlackEstimator


class MPCPlanner:
    def __init__(self, params: StrategyParams, cargo_prior: CargoPrior) -> None:
        self.params = params
        self.prior = cargo_prior
        self.calibrator = PenaltyCalibrator(params)
        self.slack = ConstraintSlackEstimator(params)

    def choose(
        self,
        status: dict[str, Any],
        preferences: dict[str, Any],
        history: dict[str, Any],
        scored_orders: list[Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        automata = ConstraintAutomata(preferences, self.params)
        best = None
        best_score = float("-inf")
        evaluated = 0
        for scored in scored_orders[: max(1, int(self.params.mpc_top_k))]:
            item = scored.item
            start = int(item.get("action_start_minute", status.get("simulation_progress_minutes", 0)))
            end = int(item.get("estimated_finish_minute", start))
            check = automata.check_order(status, history, item, start, end)
            if not check.allowed or not automata.future_feasibility(item, end):
                continue
            candidate_slack = self.slack.estimate_after_order(status, preferences, history, item)
            if candidate_slack["overall_slack_level"] == "blocked":
                continue
            cargo = item.get("cargo") or {}
            destination = str((cargo.get("end") or {}).get("city") or "")
            future = self.prior.destination_value(destination) * self.params.future_value_weight
            future += self.prior.score_bonus((end // 60) % 24, destination, str(cargo.get("cargo_name") or ""))
            slack_values = [
                x
                for x in (
                    candidate_slack.get("required_stop_slack_minutes"),
                    candidate_slack.get("home_slack_minutes"),
                    candidate_slack.get("daily_rest_slack_minutes"),
                )
                if x is not None
            ]
            slack_risk = sum(max(0.0, 360.0 - float(x)) for x in slack_values)
            risk_penalty = check.risk * self.params.unknown_risk_lambda * 100.0
            query_cost_penalty = int(item.get("action_start_minute", start)) - int(status.get("simulation_progress_minutes", start))
            value = (
                float(scored.score)
                + future
                - risk_penalty
                - slack_risk * self.params.slack_risk_penalty_weight
                - query_cost_penalty * self.params.query_cost_penalty_weight
            )
            evaluated += 1
            if value > best_score:
                best_score, best = value, scored
        debug = {"mpc_evaluated": evaluated, "mpc_best_value": round(best_score, 2) if best else None}
        if best is None:
            return None, debug
        return {"action": "take_order", "params": {"cargo_id": best.cargo_id}}, {**debug, "mpc_selected_cargo_id": best.cargo_id}
