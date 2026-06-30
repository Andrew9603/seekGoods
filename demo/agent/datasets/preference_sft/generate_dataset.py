from __future__ import annotations

import hashlib
import json
import random
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SEED = 20260623

CATEGORIES = ["蔬菜", "机械设备", "冷链食品", "玻璃制品", "危险品", "家具家居", "数码家电", "煤炭矿产"]
REGIONS = ["深圳", "惠州", "广州", "佛山", "东莞", "中山", "江门", "清远", "肇庆"]

SYSTEM_PROMPT = (
    "你是货运司机偏好解析器。将司机的中文自然语言要求转换为给定 JSON 结构。"
    "不得放宽硬约束；无法可靠结构化的强制要求放入 unknown_hard_constraints。只输出 JSON。"
)


def empty_constraints() -> dict[str, Any]:
    return {
        "hard_ban_categories": [],
        "soft_avoid_categories": [],
        "daily_rest": {"min_continuous_minutes": None},
        "scheduled_rest_windows": [],
        "monthly_off_days": None,
        "max_pickup_deadhead_km": None,
        "max_haul_km": None,
        "required_region_order_days": [],
        "forbidden_regions": [],
        "avoid_regions": [],
        "required_location_stops": [],
        "home_rules": [],
        "allowed_regions": [],
        "unknown_hard_constraints": [],
        "unknown_soft_constraints": [],
        "requires_conservative_mode": False,
    }


def merge_labels(parts: list[dict[str, Any]]) -> dict[str, Any]:
    out = empty_constraints()
    list_keys = [
        "hard_ban_categories",
        "soft_avoid_categories",
        "scheduled_rest_windows",
        "required_region_order_days",
        "forbidden_regions",
        "avoid_regions",
        "required_location_stops",
        "home_rules",
        "allowed_regions",
        "unknown_hard_constraints",
        "unknown_soft_constraints",
    ]
    for part in parts:
        for key in list_keys:
            out[key].extend(deepcopy(part.get(key) or []))
        rest = (part.get("daily_rest") or {}).get("min_continuous_minutes")
        if rest:
            out["daily_rest"]["min_continuous_minutes"] = max(
                int(out["daily_rest"]["min_continuous_minutes"] or 0), int(rest)
            )
        for key in ("monthly_off_days",):
            if part.get(key):
                out[key] = max(int(out.get(key) or 0), int(part[key]))
        for key in ("max_pickup_deadhead_km", "max_haul_km"):
            if part.get(key):
                values = [float(x) for x in (out.get(key), part[key]) if x is not None]
                out[key] = min(values)
        out["requires_conservative_mode"] = bool(
            out["requires_conservative_mode"] or part.get("requires_conservative_mode")
        )
    for key in list_keys:
        seen, unique = set(), []
        for value in out[key]:
            signature = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if signature not in seen:
                seen.add(signature)
                unique.append(value)
        out[key] = unique
    return out


def rule_factories(split: str):
    wording = {
        "train": {
            "hard_category": [
                "{category}一律不能接，看到就跳过。",
                "别给我派{category}，接一次就要扣钱。",
                "{category}这类活我干不了，全部推掉。",
            ],
            "soft_category": [
                "我不太想拉{category}，收益特别好再考虑。",
                "{category}尽量少接，不是完全禁止。",
            ],
            "rest_window": [
                "每天{start}到次日{end}不接单也不空驶。",
                "夜里{start}以后停车休息，早上{end}再出车。",
            ],
            "daily_rest": [
                "每天至少连续停车休息{hours}小时。",
                "一天里必须保证不间断睡满{hours}个小时。",
            ],
            "off_days": [
                "这个月至少留{days}个整天完全不出车。",
                "每月要有{days}天从零点到二十四点都停车。",
            ],
            "region_ban": [
                "装货地或卸货地在{region}的单都不接。",
                "{region}我一律不去，也别给我派进去。",
            ],
            "dated_region_ban": [
                "3月{day}日不能进{region}。",
                "三月{day}号当天不要给我派往{region}的货。",
            ],
            "pickup_limit": [
                "接货时赶往装货点的空驶不能超过{km}公里。",
                "去装货地超过{km}km的单直接放弃。",
            ],
            "haul_limit": [
                "单趟干线运输不超过{km}公里。",
                "超过{km}km的长途单不要接。",
            ],
            "region_days": [
                "这个月至少要在{region}完成{days}个不同日期的订单。",
                "自然月里与{region}相关的订单至少覆盖{days}天。",
            ],
            "required_stop": [
                "3月{day}日{hour}点前到{lat},{lng}停留{stay}分钟。",
                "三月{day}号最晚{hour}:00抵达坐标{lat}，{lng}，停车{stay}分钟。",
            ],
            "home": [
                "每天{deadline}点前必须回家，次日{until}点前不接单也不空驶。",
                "每晚最迟{deadline}:00到家，第二天{until}点以前都不出车。",
            ],
            "only_region": [
                "我只在{region}范围内跑，不能离开。",
                "订单起终点都必须在{region}，其他地方不去。",
            ],
        },
        "val": {
            "hard_category": ["{category}碰都别碰，平台有这类货就替我过滤。"],
            "soft_category": ["能不拉{category}就不拉，但价格足够高可以商量。"],
            "rest_window": ["{start}至翌日{end}是固定睡眠时间，车必须停着。"],
            "daily_rest": ["无论多忙，每日连续熄火时间不能少于{hours}小时。"],
            "off_days": ["全月安排{days}个完整停运日，全天不动车。"],
            "region_ban": ["凡是涉及{region}装卸的业务都排除。"],
            "dated_region_ban": ["仅在3月{day}号避开{region}，其他日期正常。"],
            "pickup_limit": ["装货前的无货行驶上限是{km}公里。"],
            "haul_limit": ["一单的运输里程封顶{km}公里。"],
            "region_days": ["月内至少{days}个自然日在{region}装货或卸货。"],
            "required_stop": ["务必于3月{day}日{hour}时前到达({lat},{lng})并驻留{stay}分钟。"],
            "home": ["每日须在{deadline}时之前返家，并停驶至翌日{until}时。"],
            "only_region": ["活动范围限定为{region}，不得跨出该区域。"],
        },
        "test": {
            "hard_category": ["{category}风险太大，不管多少钱都不要替我接。"],
            "soft_category": ["对{category}我有点顾虑，条件一般时优先选别的货。"],
            "rest_window": ["从晚上{start}开始收车，一直到第二天早晨{end}才重新开工。"],
            "daily_rest": ["每天必须留出完整连续的{hours}小时恢复体力。"],
            "off_days": ["整个月至少歇足{days}个全天，期间任何驾驶行为都不要有。"],
            "region_ban": ["路线只要以{region}为起点或终点，就不要考虑。"],
            "dated_region_ban": ["{region}平时能去，唯独三月{day}号不能进入。"],
            "pickup_limit": ["我愿意接单，但到提货点的空车距离最多{km}公里。"],
            "haul_limit": ["线路里程若高于{km}公里就算长途，我不跑。"],
            "region_days": ["本月需要在{days}个不同日期照应{region}的业务。"],
            "required_stop": ["{day}号有事，{hour}点前必须赶到经纬度{lat}/{lng}，至少待{stay}分钟。"],
            "home": ["我得在夜里{deadline}点以前到家，早晨{until}点后才能再次出发。"],
            "only_region": ["我的运营边界只有{region}，超出边界的货全部拒绝。"],
        },
    }[split]

    def make(kind: str, rng: random.Random) -> tuple[str, dict[str, Any], dict[str, Any]]:
        template = rng.choice(wording[kind])
        label = empty_constraints()
        values: dict[str, Any] = {}
        if kind in {"hard_category", "soft_category"}:
            values["category"] = rng.choice(CATEGORIES)
            label["hard_ban_categories" if kind == "hard_category" else "soft_avoid_categories"] = [
                values["category"]
            ]
        elif kind == "rest_window":
            start = rng.choice([20, 21, 22, 23, 0, 1, 2])
            end = rng.choice([5, 6, 7, 8, 9])
            if start < 10:
                start = rng.choice([0, 1, 2])
                end = rng.choice([5, 6, 7])
            values.update(start=f"{start}:00", end=f"{end}:00")
            label["scheduled_rest_windows"] = [{"start_minute": start * 60, "end_minute": end * 60}]
        elif kind == "daily_rest":
            values["hours"] = rng.choice([5, 6, 7, 8, 9])
            label["daily_rest"]["min_continuous_minutes"] = values["hours"] * 60
        elif kind == "off_days":
            values["days"] = rng.choice([1, 2, 3, 4, 5])
            label["monthly_off_days"] = values["days"]
        elif kind in {"region_ban", "dated_region_ban", "region_days", "only_region"}:
            values["region"] = rng.choice(REGIONS)
            if kind == "region_ban":
                label["forbidden_regions"] = [{"region": values["region"], "days": None}]
            elif kind == "dated_region_ban":
                values["day"] = rng.randint(3, 28)
                label["forbidden_regions"] = [{"region": values["region"], "days": [values["day"]]}]
            elif kind == "region_days":
                values["days"] = rng.choice([2, 3, 4, 5, 6])
                label["required_region_order_days"] = [
                    {"region": values["region"], "min_days": values["days"]}
                ]
            else:
                label["allowed_regions"] = [values["region"]]
        elif kind in {"pickup_limit", "haul_limit"}:
            values["km"] = rng.choice([30, 40, 50, 55, 60, 80] if kind == "pickup_limit" else [100, 120, 150, 180, 220, 250])
            label["max_pickup_deadhead_km" if kind == "pickup_limit" else "max_haul_km"] = float(values["km"])
        elif kind == "required_stop":
            values.update(
                day=rng.randint(3, 29),
                hour=rng.choice([8, 9, 10, 12, 14, 18]),
                lat=round(rng.uniform(22.5, 24.0), 2),
                lng=round(rng.uniform(112.8, 114.8), 2),
                stay=rng.choice([30, 60, 90, 120]),
            )
            label["required_location_stops"] = [{
                "day": values["day"],
                "latitude": values["lat"],
                "longitude": values["lng"],
                "region": "",
                "min_stop_minutes": values["stay"],
                "deadline_minute_of_day": values["hour"] * 60,
                "earliest_minute_of_day": None,
            }]
        elif kind == "home":
            values["deadline"] = rng.choice([20, 21, 22, 23])
            values["until"] = rng.choice([6, 7, 8, 9])
            label["home_rules"] = [{
                "deadline_minute": values["deadline"] * 60,
                "stay_until_minute": values["until"] * 60,
                "home_location": None,
                "home_location_source": "initial_position_or_explicit_coordinate",
            }]
        return template.format(**values), label, {"rule_type": kind, "values": values}

    return make


RULE_TYPES = [
    "hard_category", "soft_category", "rest_window", "daily_rest", "off_days",
    "region_ban", "dated_region_ban", "pickup_limit", "haul_limit", "region_days",
    "required_stop", "home", "only_region",
]


def build_record(split: str, index: int, rng: random.Random) -> dict[str, Any]:
    make = rule_factories(split)
    count_weights = [1] * 20 + [2] * 50 + [3] * 25 + [4] * 5
    count = rng.choice(count_weights)
    kinds = rng.sample(RULE_TYPES, count)
    pieces, labels, metadata = [], [], []
    for kind in kinds:
        text, label, meta = make(kind, rng)
        pieces.append(text)
        labels.append(label)
        metadata.append(meta)
    rng.shuffle(pieces)
    text = rng.choice([" ".join(pieces), "；".join(pieces), "\n".join(pieces)])
    constraints = merge_labels(labels)
    record_id = f"{split}-{index:05d}"
    return {
        "id": record_id,
        "text": text,
        "constraints": constraints,
        "metadata": {
            "source": "synthetic",
            "split": split,
            "rule_types": sorted(kinds),
            "components": metadata,
            "generator_seed": SEED,
        },
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
            {"role": "assistant", "content": json.dumps(constraints, ensure_ascii=False, sort_keys=True)},
        ],
    }


def build_challenge(index: int, rng: random.Random) -> dict[str, Any]:
    known_text, known_label, meta = rule_factories("test")(rng.choice(RULE_TYPES), rng)
    unknowns = [
        "这几天必须按我约定的路线走，具体路线临时通知，违反要扣钱。",
        "月底前一定要把欠的人情单跑完，但名单我之后再说。",
        "遇到天气不对就按老规矩停运，平台应该知道老规矩是什么。",
        "家里来电话时必须马上回去，地点以电话里说的为准。",
        "货主评级低于我心里的标准一律不接。",
    ]
    unknown = rng.choice(unknowns)
    label = merge_labels([known_label])
    label["unknown_hard_constraints"] = [unknown]
    label["requires_conservative_mode"] = True
    text = f"{known_text} {unknown}"
    return {
        "id": f"challenge-{index:05d}",
        "text": text,
        "constraints": label,
        "metadata": {
            "source": "synthetic_challenge",
            "split": "challenge",
            "rule_types": [meta["rule_type"], "unknown_hard"],
            "generator_seed": SEED,
        },
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
            {"role": "assistant", "content": json.dumps(label, ensure_ascii=False, sort_keys=True)},
        ],
    }


PUBLIC_SEEDS = [
    ("每天至少连续停车熄火休息满8小时。", {"daily_rest": {"min_continuous_minutes": 480}}),
    ("机械设备这类活儿我干不了，每接一次都要扣钱。", {"hard_ban_categories": ["机械设备"]}),
    ("装货地或卸货地在惠州的货，我一律不接。", {"forbidden_regions": [{"region": "惠州", "days": None}]}),
    ("三月得抽三个整天完全歇着。", {"monthly_off_days": 3}),
    ("三月四号五号不往深圳跑。", {"forbidden_regions": [{"region": "深圳", "days": [4, 5]}]}),
    ("零点以后到早上六点车得停着。", {"scheduled_rest_windows": [{"start_minute": 0, "end_minute": 360}]}),
    ("凡是蔬菜货源我一律推掉。", {"hard_ban_categories": ["蔬菜"]}),
    ("自然月里增城相关订单起码覆盖四个不同日子。", {"required_region_order_days": [{"region": "增城", "min_days": 4}]}),
    ("赶去装货那一程空驶不能超过五十五公里。", {"max_pickup_deadhead_km": 55.0}),
    ("这月起码留两个整天停驶检修。", {"monthly_off_days": 2}),
    ("三月十二号到增城停两小时。", {"required_location_stops": [{"day": 12, "latitude": 23.15, "longitude": 113.67, "region": "增城", "min_stop_minutes": 120, "deadline_minute_of_day": 1080, "earliest_minute_of_day": None}]}),
    ("三月三十一号先到增城，再在十二点前赶到四会并待到下午两点。", {"required_location_stops": [{"day": 31, "latitude": 23.15, "longitude": 113.67, "region": "增城", "min_stop_minutes": 1, "deadline_minute_of_day": 720, "earliest_minute_of_day": None}, {"day": 31, "latitude": 23.32, "longitude": 112.83, "region": "四会", "min_stop_minutes": 120, "deadline_minute_of_day": 720, "earliest_minute_of_day": 720}]}),
]


def public_seed_records() -> list[dict[str, Any]]:
    rows = []
    for index, (text, partial) in enumerate(PUBLIC_SEEDS, 1):
        label = merge_labels([partial])
        rows.append({
            "id": f"public-seed-{index:02d}",
            "text": text,
            "constraints": label,
            "metadata": {"source": "public_competition_seed", "split": "seed_only"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
                {"role": "assistant", "content": json.dumps(label, ensure_ascii=False, sort_keys=True)},
            ],
        })
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def validate(all_splits: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    text_hashes: dict[str, str] = {}
    duplicate_texts = []
    distribution: dict[str, dict[str, int]] = {}
    for split, rows in all_splits.items():
        distribution[split] = {}
        for row in rows:
            normalized = "".join(str(row["text"]).split())
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            if digest in text_hashes:
                duplicate_texts.append([text_hashes[digest], row["id"]])
            text_hashes[digest] = row["id"]
            assert row["messages"][2]["content"] == json.dumps(
                row["constraints"], ensure_ascii=False, sort_keys=True
            )
            for kind in row["metadata"].get("rule_types", []):
                distribution[split][kind] = distribution[split].get(kind, 0) + 1
    return {
        "seed": SEED,
        "counts": {key: len(value) for key, value in all_splits.items()},
        "duplicate_text_count": len(duplicate_texts),
        "duplicate_examples": duplicate_texts[:10],
        "rule_distribution": distribution,
        "schema": "seekgoods_preference_constraints_v1",
    }


def main() -> None:
    counts = {"train": 2500, "val": 300, "test": 400}
    splits: dict[str, list[dict[str, Any]]] = {}
    seen_texts: set[str] = set()
    for offset, (split, count) in enumerate(counts.items()):
        rng = random.Random(SEED + offset)
        rows = []
        attempts = 0
        while len(rows) < count:
            attempts += 1
            if attempts > count * 100:
                raise RuntimeError(f"cannot generate enough unique rows for {split}")
            row = build_record(split, len(rows) + 1, rng)
            normalized = "".join(row["text"].split())
            if normalized in seen_texts:
                continue
            seen_texts.add(normalized)
            rows.append(row)
        splits[split] = rows
    challenge_rng = random.Random(SEED + 99)
    challenge_rows = []
    attempts = 0
    while len(challenge_rows) < 200:
        attempts += 1
        if attempts > 20000:
            raise RuntimeError("cannot generate enough unique challenge rows")
        row = build_challenge(len(challenge_rows) + 1, challenge_rng)
        normalized = "".join(row["text"].split())
        if normalized in seen_texts:
            continue
        seen_texts.add(normalized)
        challenge_rows.append(row)
    splits["challenge"] = challenge_rows
    seeds = public_seed_records()

    for split, rows in splits.items():
        write_jsonl(ROOT / f"{split}.jsonl", rows)
        write_jsonl(
            ROOT / f"{split}_messages.jsonl",
            [{"id": row["id"], "messages": row["messages"]} for row in rows],
        )
    write_jsonl(ROOT / "public_seeds.jsonl", seeds)
    report = validate(splits)
    report["public_seed_count"] = len(seeds)
    (ROOT / "dataset_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["counts"], ensure_ascii=False))
    print(f"duplicate_text_count={report['duplicate_text_count']}")


if __name__ == "__main__":
    main()
