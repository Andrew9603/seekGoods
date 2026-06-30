from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "demo" / "agent" / "config" / "stress_preferences.jsonl"
REGIONS = ["惠州", "深圳", "佛山", "广州", "东莞", "清远", "肇庆"]
CATEGORIES = ["冷链", "玻璃", "危险品", "生鲜", "机械设备"]


def generate_one(rng: random.Random, index: int) -> dict:
    day = rng.randint(6, 27)
    region_a, region_b = rng.sample(REGIONS, 2)
    category = rng.choice(CATEGORIES)
    lat = round(rng.uniform(22.6, 23.9), 2)
    lng = round(rng.uniform(112.9, 114.6), 2)
    scenarios = [
        f"3月{day}日和3月{day + 1}日不能进{region_a}，3月{day + 3}日不能去{region_b}。",
        f"3月{day}日10点前到 {lat},{lng} 停留60分钟，每天23点前回家，次日7点前不跑。",
        "每天连续休息8小时，长途收益再高也不能影响休息。",
        "必须按我说的临时路线走，违反会扣罚，具体路线稍后再说。",
        f"只在{region_a}跑，外面的高价单也不能接。",
        f"尽量不拉{category}，但高收益时可以权衡；赶装货点不能超过60公里。",
    ]
    selected = rng.sample(scenarios, rng.randint(3, 5))
    return {"synthetic_id": f"STRESS{index:04d}", "preferences": [{"content": " ".join(selected)}]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260607)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        for index in range(1, max(1, args.count) + 1):
            fh.write(json.dumps(generate_one(rng, index), ensure_ascii=False) + "\n")
    print(f"wrote {args.count} stress preferences to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
