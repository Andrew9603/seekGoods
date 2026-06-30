from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SYSTEM_PROMPT = (
    "你是货运找货比赛中的决策排序模型。给定司机状态、约束余量、候选货源分数和风险信息，"
    "选择更适合当前轮次的动作。目标是在避免偏好罚分和动作校验失败的前提下最大化最终净收益。"
    "只输出 JSON。"
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def action_cargo_id(action: dict[str, Any] | None) -> str | None:
    if not isinstance(action, dict):
        return None
    if action.get("action") != "take_order":
        return None
    params = action.get("params") or {}
    cargo_id = params.get("cargo_id")
    return str(cargo_id) if cargo_id is not None else None


def compact_state(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "driver_id": record.get("driver_id"),
        "minute": record.get("simulation_progress_minutes"),
        "risk_level": record.get("risk_level"),
        "adaptive_mode": record.get("adaptive_mode"),
        "active_hard_constraints": record.get("active_hard_constraints") or [],
        "constraint_slack": record.get("constraint_slack") or {},
        "query_k": record.get("query_k"),
        "filtered_count": record.get("filtered_count"),
        "firewall_blocked_count": record.get("firewall_blocked_count"),
    }


def compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "cargo_id": str(candidate.get("cargo_id")),
        "score": candidate.get("score"),
        "net_profit": candidate.get("net_profit"),
        "preference_tradeoffs": candidate.get("preference_tradeoffs") or [],
    }


def response_for(candidate: dict[str, Any], decision_type: str, rationale: str) -> str:
    payload = {
        "action": "take_order",
        "cargo_id": str(candidate.get("cargo_id")),
        "decision_type": decision_type,
        "rationale": rationale,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def build_pairs(records: list[dict[str, Any]], source_name: str) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for idx, record in enumerate(records):
        top = record.get("top_5_order_scores") or []
        if len(top) < 2:
            continue
        selected_id = action_cargo_id(record.get("selected_action"))
        if not selected_id:
            continue
        selected = next((c for c in top if str(c.get("cargo_id")) == selected_id), None)
        if not selected:
            continue
        rejected_candidates = [c for c in top if str(c.get("cargo_id")) != selected_id]
        if not rejected_candidates:
            continue

        state = compact_state(record)
        candidates = [compact_candidate(c) for c in top]
        prompt_payload = {
            "state": state,
            "candidates": candidates,
            "instruction": "从候选货源中选择当前轮次更优动作，重点考虑最终得分、硬约束风险、约束余量和未来可行性。",
        }
        prompt = json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)
        chosen_reason = (
            "MPC/策略回放选择该货源，综合当前收益、约束余量、未来区域机会和风险后更有利于最终得分。"
        )
        for rejected in rejected_candidates[:2]:
            reject_score = float(rejected.get("score") or 0.0)
            chosen_score = float(selected.get("score") or 0.0)
            if reject_score > chosen_score:
                rejected_reason = "该货源即时分数更高，但滚动规划后可能破坏后续约束空间或未来收益。"
                pair_type = "mpc_overrides_greedy"
            else:
                rejected_reason = "该货源综合收益、未来机会或约束安全性弱于 chosen。"
                pair_type = "ranked_lower"
            pairs.append(
                {
                    "id": f"{source_name}-{idx:05d}-{len(pairs):05d}",
                    "pair_type": pair_type,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "prompt": prompt,
                    "chosen": response_for(selected, "chosen", chosen_reason),
                    "rejected": response_for(rejected, "rejected", rejected_reason),
                    "metadata": {
                        "source": source_name,
                        "driver_id": record.get("driver_id"),
                        "minute": record.get("simulation_progress_minutes"),
                        "selected_cargo_id": selected_id,
                        "rejected_cargo_id": str(rejected.get("cargo_id")),
                        "chosen_score": selected.get("score"),
                        "rejected_score": rejected.get("score"),
                        "adaptive_mode": record.get("adaptive_mode"),
                        "risk_level": record.get("risk_level"),
                    },
                }
            )
    return pairs


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--debug-dir",
        type=Path,
        default=Path("demo/results/experiments/robust_mpc_adaptive/agent_debug"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("demo/agent/datasets/preference_alignment"),
    )
    parser.add_argument("--val-ratio", type=float, default=0.15)
    args = parser.parse_args()

    all_pairs: list[dict[str, Any]] = []
    for path in sorted(args.debug_dir.glob("*.jsonl")):
        records = read_jsonl(path)
        all_pairs.extend(build_pairs(records, path.stem))

    split_at = max(1, int(len(all_pairs) * (1.0 - args.val_ratio)))
    train = all_pairs[:split_at]
    val = all_pairs[split_at:]
    write_jsonl(args.output_dir / "decision_pairs_train.jsonl", train)
    write_jsonl(args.output_dir / "decision_pairs_val.jsonl", val)
    report = {
        "total_pairs": len(all_pairs),
        "train_pairs": len(train),
        "val_pairs": len(val),
        "pair_type_counts": {},
    }
    for row in all_pairs:
        key = row.get("pair_type", "unknown")
        report["pair_type_counts"][key] = report["pair_type_counts"].get(key, 0) + 1
    (args.output_dir / "decision_pairs_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
