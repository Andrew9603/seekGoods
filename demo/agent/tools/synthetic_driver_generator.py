from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "demo" / "agent" / "config" / "synthetic_preferences.jsonl"
CATEGORIES = ["蔬菜", "机械设备", "冷链", "玻璃", "危险品", "生鲜", "快递", "搬家"]
REGIONS = ["惠州", "深圳", "佛山", "广州", "东莞", "清远", "肇庆"]


def generate_one(rng: random.Random, index: int) -> dict:
    category = rng.choice(CATEGORIES)
    region = rng.choice(REGIONS)
    day = rng.randint(3, 28)
    lat = round(rng.uniform(22.5, 24.0), 2)
    lng = round(rng.uniform(112.8, 114.8), 2)
    rules = [
        rng.choice([f"不接{category}，看到这类货直接跳过。", f"{category}一律不能接，接了要扣钱。"]),
        rng.choice([f"尽量不接{category}。", f"不太想拉{category}，收益特别好再考虑。"]),
        rng.choice(["每天连续休息6小时。", "每天22:00到次日08:00不接单也不空驶。", "凌晨2点到5点不跑。"]),
        f"每月至少{rng.randint(1,4)}天完全不出车。",
        rng.choice([f"不去{region}。", f"3月{day}日不能进{region}。", f"只在{region}跑。"]),
        rng.choice(["每天23点前回家，次日8点前不跑。", f"3月{day}日必须在家。"]),
        f"3月{day}日10点前到 {lat},{lng} 停留30分钟。",
        rng.choice([f"赶装货点不超过{rng.choice([40,60,80])}公里。", f"单趟不超过{rng.choice([120,180,250])}公里。", "长途不接，短途优先。"]),
        "这几天必须按约定路线走，违反会扣罚。",
    ]
    count = rng.randint(2, 5)
    selected = rng.sample(rules, count)
    return {"synthetic_id": f"SYN{index:04d}", "preferences": [{"content": " ".join(selected)}]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--seed", type=int, default=20260606)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        for i in range(max(1, args.count)):
            fh.write(json.dumps(generate_one(rng, i + 1), ensure_ascii=False) + "\n")
    print(f"wrote {args.count} synthetic preferences to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
