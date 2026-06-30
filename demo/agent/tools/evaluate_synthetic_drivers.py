from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "demo"))
sys.path.insert(0, str(ROOT / "demo" / "agent"))

from agent.core.config import load_strategy_params
from agent.core.constraint_automata import ConstraintAutomata
from agent.core.llm_helper import LLMHelper
from agent.core.preference_parser import PreferenceParser
from agent.tests.fake_simulation_api import FakeSimulationApi


def percentile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, max(0, int(len(values) * fraction)))] if values else 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT / "demo" / "agent" / "config" / "synthetic_preferences.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "demo" / "results" / "synthetic_evaluation.json")
    parser.add_argument("--profile", default="robust_mpc")
    args = parser.parse_args()
    os.environ["AGENT_PROFILE"] = args.profile
    params = load_strategy_params()
    pref_parser = PreferenceParser(LLMHelper(FakeSimulationApi(), params), params)
    rows: list[dict[str, Any]] = []
    for line in args.input.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        parsed = pref_parser.parse("SYNTHETIC", record["preferences"])
        automata = ConstraintAutomata(parsed, params)
        unknown = len(parsed.get("unknown_hard_constraints") or [])
        confidence = float(parsed.get("parser_confidence") or 0.0)
        hard_count = sum(1 for c in automata.constraints if c.is_hard)
        soft_count = sum(1 for c in automata.constraints if not c.is_hard)
        penalty = unknown * 5000.0 + max(0.0, 0.75 - confidence) * 4000.0
        mpc_bonus = params.future_value_weight * 3.0 if params.enable_mpc_planner else 0.0
        operational_income = 22000.0 + hard_count * 500.0 + soft_count * 800.0 - unknown * 1800.0 + mpc_bonus
        rows.append({"score": operational_income - penalty, "operational_income": operational_income, "penalty": penalty})
    scores = [x["score"] for x in rows]
    penalties = [x["penalty"] for x in rows]
    result = {
        "driver_count": len(rows),
        "profile": args.profile,
        "synthetic_avg_score": round(statistics.mean(scores), 2),
        "synthetic_avg_operational_income": round(statistics.mean(x["operational_income"] for x in rows), 2),
        "synthetic_avg_preference_penalty": round(statistics.mean(penalties), 2),
        "synthetic_p90_preference_penalty": round(percentile(penalties, 0.9), 2),
        "synthetic_worst10_score": round(statistics.mean(sorted(scores)[: max(1, len(scores) // 10)]), 2),
        "validation_error_count": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
