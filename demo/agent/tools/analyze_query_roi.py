from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEBUG_DIR = ROOT / "demo" / "results" / "agent_debug"
OUT_DIR = ROOT / "demo" / "results" / "experiments"


def main() -> int:
    stats: dict[int, dict[str, Any]] = defaultdict(lambda: {"queries": 0, "returned": [], "takes": 0, "profits": [], "scan": []})
    for path in DEBUG_DIR.glob("*.jsonl"):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if "query_k" not in rec:
                    continue
                k = int(rec.get("query_k") or 0)
                bucket = stats[k]
                bucket["queries"] += 1
                bucket["returned"].append(int(rec.get("returned_count") or rec.get("cargo_count") or 0))
                bucket["scan"].append(int(rec.get("query_scan_cost_minutes") or 0))
                action = rec.get("selected_action") or {}
                if action.get("action") == "take_order":
                    bucket["takes"] += 1
                    if rec.get("expected_net_profit") is not None:
                        bucket["profits"].append(float(rec["expected_net_profit"]))
    rows = []
    for k, bucket in sorted(stats.items()):
        queries = int(bucket["queries"])
        take_rate = bucket["takes"] / queries if queries else 0.0
        rows.append(
            {
                "query_k": k,
                "queries": queries,
                "avg_returned_count": round(mean(bucket["returned"]), 2) if bucket["returned"] else 0.0,
                "take_order_rate": round(take_rate, 4),
                "avg_selected_expected_net_profit": round(mean(bucket["profits"]), 2) if bucket["profits"] else 0.0,
                "avg_query_scan_cost_minutes": round(mean(bucket["scan"]), 2) if bucket["scan"] else 0.0,
            }
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "query_roi.csv"
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["query_k"])
        writer.writeheader()
        writer.writerows(rows)
    recommendation = _recommend(rows)
    (OUT_DIR / "query_roi_recommendation.txt").write_text(recommendation + "\n", encoding="utf-8")
    print(recommendation)
    return 0


def _recommend(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No query ROI data found."
    useful = [r for r in rows if float(r["take_order_rate"]) > 0]
    pool = useful or rows
    best = max(pool, key=lambda r: float(r["avg_selected_expected_net_profit"]) - float(r["avg_query_scan_cost_minutes"]) * 8.0)
    return (
        f"Suggested query_k anchor: {best['query_k']} "
        f"(take_rate={best['take_order_rate']}, avg_profit={best['avg_selected_expected_net_profit']}, "
        f"scan_minutes={best['avg_query_scan_cost_minutes']})."
    )


if __name__ == "__main__":
    raise SystemExit(main())
