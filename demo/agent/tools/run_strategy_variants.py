from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "demo"
SERVER = DEMO / "server"
RESULTS = DEMO / "results"
EXPERIMENTS = RESULTS / "experiments"
PROFILES_PATH = DEMO / "agent" / "config" / "strategy_profiles.json"
DEFAULT_MODEL_URL = "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    selected = argv or ["strict_compliance", "balanced", "profit_aggressive", "hidden_robust", "online_robust"]
    profiles = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    EXPERIMENTS.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for name in selected:
        if name not in profiles:
            raise SystemExit(f"Unknown profile: {name}")
        print(f"=== Running profile: {name} ===", flush=True)
        _clear_active_results()
        env = os.environ.copy()
        env["AGENT_STRATEGY_PROFILE"] = name
        env["AGENT_STRATEGY_PROFILES_PATH"] = str(PROFILES_PATH)
        model_url = env.get("AGENT_MODEL_API_URL", DEFAULT_MODEL_URL)
        subprocess.run(
            [
                sys.executable,
                "main.py",
                "--model-api-url",
                model_url,
                "--simulation-days",
                "31",
            ],
            cwd=SERVER,
            env=env,
            check=True,
        )
        subprocess.run([sys.executable, "calc_monthly_income.py"], cwd=DEMO, env=env, check=True)
        profile_dir = EXPERIMENTS / name
        _copy_results(profile_dir)
        row = _summarize(profile_dir, name)
        rows.append(row)
        print(f"{name}: net={row['total_net_income_all_drivers']} penalty={row['total_preference_penalty']} failed={row['failed_driver_count']}", flush=True)
    _write_summary(rows)
    best = _best_profile(rows)
    (EXPERIMENTS / "best_profile.txt").write_text(best + "\n", encoding="utf-8")
    print(f"best_profile={best}", flush=True)
    return 0


def _clear_active_results() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    for path in RESULTS.glob("actions_202603_*.jsonl"):
        path.unlink(missing_ok=True)
    for name in ("monthly_income_202603.json", "run_summary_202603.json"):
        (RESULTS / name).unlink(missing_ok=True)
    for name in ("agent_debug", "history", "logs"):
        path = RESULTS / name
        if path.exists():
            shutil.rmtree(path)


def _copy_results(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    for path in RESULTS.iterdir():
        if path.name == "experiments":
            continue
        dest = target / path.name
        if path.is_dir():
            shutil.copytree(path, dest)
        else:
            shutil.copy2(path, dest)


def _summarize(profile_dir: Path, profile: str) -> dict[str, Any]:
    data = json.loads((profile_dir / "monthly_income_202603.json").read_text(encoding="utf-8"))
    summary = data.get("summary", {})
    action_stats = _action_stats(profile_dir)
    risk_levels = _risk_levels(profile_dir)
    net_income = float(summary.get("total_net_income_all_drivers", 0.0))
    preference_penalty = float(summary.get("total_preference_penalty", 0.0))
    row: dict[str, Any] = {
        "profile": profile,
        "total_net_income_all_drivers": net_income,
        "final_score": net_income,
        "total_preference_penalty": preference_penalty,
        "operational_income": net_income + preference_penalty,
        "failed_driver_count": int(summary.get("failed_driver_count", 0)),
        "total_tokens": int((summary.get("total_token_usage") or {}).get("total_tokens", 0) or 0),
        **action_stats,
        "risk_levels": json.dumps(risk_levels, ensure_ascii=False, sort_keys=True),
    }
    row["avg_net_income_per_order"] = net_income / max(int(action_stats["order_count"]), 1)
    for driver in data.get("drivers", []):
        driver_id = str(driver.get("driver_id"))
        income = driver.get("income") or {}
        token_usage = driver.get("token_usage") or {}
        row[f"{driver_id}_net_income"] = float(income.get("net_income", 0.0))
        row[f"{driver_id}_preference_penalty"] = float(income.get("preference_penalty", 0.0))
        row[f"{driver_id}_validation_error"] = driver.get("validation_error") or ""
        row[f"{driver_id}_tokens"] = int(token_usage.get("total_tokens", 0) or 0)
    return row


def _action_stats(profile_dir: Path) -> dict[str, Any]:
    counts = {"take_order": 0, "wait": 0, "reposition": 0}
    minutes = {"take_order": 0, "wait": 0, "reposition": 0}
    query_scan = 0
    for path in profile_dir.glob("actions_202603_*.jsonl"):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                action = str((record.get("action") or {}).get("action") or "")
                query_scan += int(record.get("query_scan_cost_minutes") or 0)
                if action in counts:
                    counts[action] += 1
                    minutes[action] += int(record.get("action_exec_cost_minutes") or 0)
    orders = counts["take_order"]
    return {
        "order_count": orders,
        "avg_orders": orders / max(len(list(profile_dir.glob("actions_202603_*.jsonl"))), 1),
        "avg_net_income_per_order": 0.0,
        "avg_order_duration_minutes": minutes["take_order"] / max(orders, 1),
        "query_scan_cost_minutes": query_scan,
        "wait_minutes": minutes["wait"],
        "take_order_minutes": minutes["take_order"],
        "reposition_minutes": minutes["reposition"],
    }


def _risk_levels(profile_dir: Path) -> dict[str, int]:
    levels: dict[str, str] = {}
    debug_dir = profile_dir / "agent_debug"
    if debug_dir.is_dir():
        for path in debug_dir.glob("*.jsonl"):
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    if record.get("risk_level"):
                        levels[path.stem] = str(record["risk_level"])
                        break
    counts: dict[str, int] = {}
    for value in levels.values():
        counts[value] = counts.get(value, 0) + 1
    return counts


def _write_summary(rows: list[dict[str, Any]]) -> None:
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    path = EXPERIMENTS / "summary.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _best_profile(rows: list[dict[str, Any]]) -> str:
    def sort_key(row: dict[str, Any]) -> tuple[int, float, float]:
        failed = int(row.get("failed_driver_count", 0))
        return (0 if failed == 0 else 1, -float(row.get("total_net_income_all_drivers", 0.0)), float(row.get("total_preference_penalty", 0.0)))

    return str(sorted(rows, key=sort_key)[0]["profile"]) if rows else ""


if __name__ == "__main__":
    raise SystemExit(main())
