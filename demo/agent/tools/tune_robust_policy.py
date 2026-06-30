from __future__ import annotations

import itertools
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    candidates = []
    for query_k, future_weight, soft_lambda, unknown_lambda, margin in itertools.product(
        [160, 200, 240], [120, 180, 240], [0.8, 1.0, 1.6], [6.0, 8.0, 12.0], [120, 180, 240]
    ):
        robustness = unknown_lambda * 120 + margin * 2
        income_proxy = query_k * 15 + future_weight * 8 - soft_lambda * 300
        candidates.append(
            {
                "query_k_default": query_k,
                "future_value_weight": future_weight,
                "soft_preference_lambda": soft_lambda,
                "unknown_risk_lambda": unknown_lambda,
                "deadline_safety_margin": margin,
                "proxy_score": round(income_proxy + robustness, 2),
            }
        )
    best = max(candidates, key=lambda x: x["proxy_score"])
    path = ROOT / "demo" / "results" / "robust_policy_search.json"
    path.write_text(json.dumps({"best": best, "evaluated": len(candidates)}, indent=2), encoding="utf-8")
    print(json.dumps(best))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
