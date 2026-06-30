from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "demo" / "server" / "data" / "cargo_dataset.jsonl"
TARGET = ROOT / "demo" / "agent" / "config" / "cargo_prior.json"


def _bucket() -> dict[str, float]:
    return {"count": 0.0, "price": 0.0, "duration": 0.0, "profit_per_hour": 0.0}


def _price_yuan(value: Any) -> float:
    price = float(value or 0.0)
    return price / 100.0 if price > 1_000_000 else price


def _add(bucket: dict[str, float], price: float, duration: float) -> None:
    bucket["count"] += 1.0
    bucket["price"] += price
    bucket["duration"] += duration
    bucket["profit_per_hour"] += price / max(duration / 60.0, 0.25)


def _finish(stats: dict[str, dict[str, float]], bonus_cap: float) -> dict[str, dict[str, float]]:
    rows: dict[str, dict[str, float]] = {}
    max_count = max((x["count"] for x in stats.values()), default=1.0)
    all_pph = sum(x["profit_per_hour"] for x in stats.values()) / max(
        sum(x["count"] for x in stats.values()), 1.0
    )
    for key, value in stats.items():
        count = max(value["count"], 1.0)
        density = value["count"] / max_count
        avg_pph = value["profit_per_hour"] / count
        rows[key] = {
            "count": int(value["count"]),
            "density": round(density, 5),
            "avg_price": round(value["price"] / count, 2),
            "avg_duration_minutes": round(value["duration"] / count, 2),
            "avg_profit_per_hour": round(avg_pph, 2),
            "bonus": round(bonus_cap * (0.55 * density + 0.45 * min(2.0, avg_pph / max(all_pph, 1.0)) / 2.0), 2),
        }
    return rows


def main() -> int:
    hour: dict[str, dict[str, float]] = defaultdict(_bucket)
    region: dict[str, dict[str, float]] = defaultdict(_bucket)
    destination: dict[str, dict[str, float]] = defaultdict(_bucket)
    category: dict[str, dict[str, float]] = defaultdict(_bucket)
    records = 0
    with SOURCE.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                cargo = json.loads(line)
                created = datetime.fromisoformat(str(cargo["create_time"]))
                price = _price_yuan(cargo.get("price"))
                duration = max(1.0, float(cargo.get("cost_time_minutes") or 1.0))
            except Exception:
                continue
            start_city = str((cargo.get("start") or {}).get("city") or "")
            end_city = str((cargo.get("end") or {}).get("city") or "")
            cargo_name = str(cargo.get("cargo_name") or "")
            _add(hour[str(created.hour)], price, duration)
            if start_city:
                _add(region[start_city], price, duration)
            if end_city:
                _add(destination[end_city], price, duration)
            if cargo_name:
                _add(category[cargo_name], price, duration)
            records += 1

    hour_rows = _finish(hour, 120.0)
    region_rows = _finish(region, 120.0)
    destination_rows = _finish(destination, 180.0)
    category_rows = _finish(category, 120.0)
    for row in destination_rows.values():
        row["opportunity_value"] = round(2.5 * float(row["density"]), 5)
    query_k = {}
    for key in map(str, range(24)):
        density = float(hour_rows.get(key, {}).get("density", 0.0))
        query_k[key] = 300 if density >= 0.65 else 200 if density >= 0.25 else 100
    payload = {
        "schema_version": 1,
        "record_count": records,
        "hour_prior": hour_rows,
        "region_prior": region_rows,
        "destination_prior": destination_rows,
        "category_prior": category_rows,
        "query_k_prior": query_k,
    }
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {TARGET} from {records} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
