from __future__ import annotations

from typing import Any


REGION_ALIASES: dict[str, list[str]] = {
    "深圳": ["深圳", "深圳市", "宝安", "龙岗", "龙华", "南山", "福田", "罗湖", "坪山", "光明", "盐田"],
    "广州": ["广州", "广州市", "白云", "黄埔", "增城", "番禺", "花都", "南沙", "天河", "越秀", "荔湾", "海珠"],
    "佛山": ["佛山", "佛山市", "南海", "顺德", "禅城", "三水", "高明"],
    "东莞": ["东莞", "东莞市", "常平", "大朗", "厚街", "凤岗", "虎门", "塘厦"],
    "惠州": ["惠州", "惠州市", "博罗", "惠城", "惠阳", "大亚湾"],
    "中山": ["中山", "中山市"],
    "江门": ["江门", "江门市", "新会", "蓬江", "江海"],
    "增城": ["增城", "增城区"],
    "四会": ["四会", "四会市"],
}

REGION_BOUNDS: dict[str, tuple[float, float, float, float]] = {
    "深圳": (22.40, 22.88, 113.72, 114.65),
    "广州": (22.45, 23.95, 112.95, 114.10),
    "佛山": (22.55, 23.60, 112.35, 113.40),
    "东莞": (22.65, 23.25, 113.50, 114.25),
    "惠州": (22.40, 24.45, 114.30, 115.55),
    "中山": (22.10, 22.85, 113.05, 113.85),
    "江门": (21.45, 22.85, 111.95, 113.35),
}


def aliases_for(region: str) -> set[str]:
    region = str(region or "")
    out = {region} if region else set()
    for canonical, aliases in REGION_ALIASES.items():
        if region == canonical or region in aliases:
            out.add(canonical)
            out.update(aliases)
    return {x for x in out if x}


def cargo_region_text(cargo: dict[str, Any]) -> str:
    parts: list[str] = []
    for endpoint in ("start", "end"):
        loc = cargo.get(endpoint) or {}
        if isinstance(loc, dict):
            for key in ("province", "city", "district", "address", "name"):
                if loc.get(key) is not None:
                    parts.append(str(loc.get(key)))
    for key in ("cargo_name", "description", "name"):
        if cargo.get(key) is not None:
            parts.append(str(cargo.get(key)))
    return " ".join(parts)


def cargo_matches_region(cargo: dict[str, Any], region: str) -> bool:
    text = cargo_region_text(cargo)
    return any(alias and alias in text for alias in aliases_for(region))


def endpoint_matches_region(cargo: dict[str, Any], endpoint: str, region: str) -> bool:
    loc = cargo.get(endpoint) or {}
    if not isinstance(loc, dict):
        return False
    text = " ".join(str(loc.get(key) or "") for key in ("province", "city", "district", "address", "name"))
    return any(alias and alias in text for alias in aliases_for(region))


def coordinate_matches_region(latitude: float, longitude: float, region: str) -> bool:
    for alias in aliases_for(region):
        bounds = REGION_BOUNDS.get(alias)
        if bounds and bounds[0] <= latitude <= bounds[1] and bounds[2] <= longitude <= bounds[3]:
            return True
    return False
