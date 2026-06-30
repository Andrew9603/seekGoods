from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .config import StrategyParams
from .llm_helper import LLMHelper


_CATEGORIES = ["机械设备", "蔬菜", "化工塑料", "煤炭矿产", "鲜活水产品", "快递快运搬家", "食品饮料", "家具家居", "数码家电"]
_REGIONS = ["惠州", "深圳", "增城", "白云", "黄埔", "南海", "顺德", "龙岗", "宝安", "博罗", "惠城", "惠阳", "东莞", "广州", "佛山"]
_REGION_COORDS = {"增城": (23.15, 113.67), "四会": (23.32, 112.83)}


def default_preferences() -> dict[str, Any]:
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
        "forbidden_action_windows": [],
        "date_region_bans": [],
        "required_stops": [],
        "only_regions": [],
        "allowed_regions": [],
        "parser_confidence": 1.0,
        "unknown_hard_constraints": [],
        "unknown_soft_constraints": [],
        "high_risk_keywords": [],
        "requires_conservative_mode": False,
        "notes": [],
    }


class PreferenceParser:
    def __init__(self, llm: LLMHelper, params: StrategyParams) -> None:
        self._llm = llm
        self._params = params
        self._cache: dict[str, dict[str, Any]] = {}

    def parse(self, driver_id: str, raw_preferences: list[Any]) -> dict[str, Any]:
        text = "\n".join(self._content(p) for p in raw_preferences if self._content(p))
        if text in self._cache:
            return dict(self._cache[text])
        parsed = self._rule_parse(text)
        parsed["_raw_text_present"] = bool(text.strip())
        parsed = self._enhance_general_chinese(parsed, text)
        if text.strip() and self._params.default_night_rest_if_preferences_exist and not parsed.get("scheduled_rest_windows"):
            parsed["scheduled_rest_windows"].append(
                {
                    "start_minute": self._params.default_night_rest_start_hour * 60,
                    "end_minute": self._params.default_night_rest_end_hour * 60,
                    "source": "submission_safe_default",
                }
            )
        if (
            text.strip()
            and (self._params.default_daily_rest_minutes_if_preferences_exist or 0) > 0
            and not (parsed.get("daily_rest") or {}).get("min_continuous_minutes")
        ):
            parsed.setdefault("daily_rest", {})["min_continuous_minutes"] = (
                self._params.default_daily_rest_minutes_if_preferences_exist
            )
            parsed["_default_daily_rest_applied"] = True
        if self._needs_llm(parsed, text):
            llm = self._llm.parse_preferences(driver_id, text)
            if llm:
                parsed = self._merge_llm_safely(parsed, llm)
            elif self._params.unknown_preference_conservative and text.strip():
                parsed["requires_conservative_mode"] = True
                parsed["_llm_parse_failed"] = True
                parsed["parser_confidence"] = min(float(parsed.get("parser_confidence", 1.0)), 0.65)
        parsed = self._finalize_safety(parsed)
        self._cache[text] = dict(parsed)
        return parsed

    def _normalize_llm_schema(self, parsed: dict[str, Any]) -> dict[str, Any]:
        list_keys = (
            "hard_ban_categories",
            "soft_avoid_categories",
            "scheduled_rest_windows",
            "required_region_order_days",
            "avoid_regions",
            "required_location_stops",
            "home_rules",
            "forbidden_action_windows",
            "date_region_bans",
            "required_stops",
            "only_regions",
            "unknown_hard_constraints",
            "unknown_soft_constraints",
        )
        for key in list_keys:
            if not isinstance(parsed.get(key), list):
                parsed[key] = []
        if not isinstance(parsed.get("daily_rest"), dict):
            parsed["daily_rest"] = {"min_continuous_minutes": None}
        parsed["home_rules"] = [rule for rule in parsed["home_rules"] if isinstance(rule, dict)]
        parsed["required_region_order_days"] = [
            rule for rule in parsed["required_region_order_days"] if isinstance(rule, dict)
        ]
        parsed["required_location_stops"] = [
            stop for stop in parsed["required_location_stops"] if isinstance(stop, dict)
        ]
        parsed["scheduled_rest_windows"] = [
            win
            for win in parsed["scheduled_rest_windows"]
            if isinstance(win, dict)
            and isinstance(win.get("start_minute"), (int, float))
            and isinstance(win.get("end_minute"), (int, float))
            and int(win["start_minute"]) != int(win["end_minute"])
        ]
        parsed["forbidden_regions"] = [
            item if isinstance(item, dict) else {"region": str(item), "days": None}
            for item in parsed["forbidden_regions"]
            if isinstance(item, (dict, str)) and item
        ]
        parsed["avoid_regions"] = [
            item if isinstance(item, dict) else {"region": str(item), "days": None}
            for item in parsed["avoid_regions"]
            if isinstance(item, (dict, str)) and item
        ]
        normalized_home_rules = []
        for rule in parsed["home_rules"]:
            try:
                deadline = self._clock_minutes(str(rule.get("deadline_time", "")))
            except ValueError:
                deadline = rule.get("deadline_minute")
            try:
                stay_until = self._clock_minutes(str(rule.get("stay_until", "")))
            except ValueError:
                stay_until = rule.get("stay_until_minute")
            if not isinstance(deadline, (int, float)):
                continue
            normalized_home_rules.append(
                {
                    "deadline_minute": int(deadline),
                    "stay_until_minute": int(stay_until) if isinstance(stay_until, (int, float)) else 8 * 60,
                    "home_location": rule.get("home_location"),
                    "home_location_source": rule.get(
                        "home_location_source", "initial_position_or_explicit_coordinate"
                    ),
                }
            )
        parsed["home_rules"] = normalized_home_rules
        for ban in parsed.get("date_region_bans") or []:
            if not isinstance(ban, dict) or not ban.get("region"):
                continue
            days = []
            for value in (ban.get("date"), ban.get("day"), ban.get("days")):
                if isinstance(value, list):
                    candidates = value
                else:
                    matches = re.findall(r"(?<![0-9])([0-9]{1,2})(?![0-9])", str(value or ""))
                    candidates = matches[-1:] if matches else []
                for candidate in candidates:
                    day = int(candidate)
                    if 1 <= day <= 31:
                        days.append(day)
            parsed["forbidden_regions"].append(
                {"region": str(ban["region"]), "days": sorted(set(days)) or None}
            )
        for win in parsed.get("forbidden_action_windows") or []:
            if not isinstance(win, dict):
                continue
            try:
                start = self._clock_minutes(str(win.get("start", "")))
                end = self._clock_minutes(str(win.get("end", "")))
            except ValueError:
                continue
            parsed["scheduled_rest_windows"].append({"start_minute": start, "end_minute": end, "source": "llm"})
        parsed.setdefault("allowed_regions", []).extend(str(x) for x in parsed.get("only_regions") or [] if x)
        for stop in parsed.get("required_stops") or []:
            if not isinstance(stop, dict) or stop.get("lat") is None or stop.get("lng") is None:
                continue
            date = str(stop.get("date", ""))
            match = re.search(r"([0-9]{1,2})$", date)
            if not match:
                continue
            try:
                deadline = self._clock_minutes(str(stop.get("deadline_time", "18:00")))
            except ValueError:
                deadline = 18 * 60
            parsed["required_location_stops"].append(
                {
                    "day": int(match.group(1)),
                    "latitude": float(stop["lat"]),
                    "longitude": float(stop["lng"]),
                    "region": "",
                    "min_stop_minutes": int(stop.get("min_stay_minutes") or 60),
                    "deadline_minute_of_day": deadline,
                    "earliest_minute_of_day": None,
                    "sequence": int(stop.get("sequence") or 1),
                }
            )
        return self._dedupe(parsed)

    @staticmethod
    def _clock_minutes(text: str) -> int:
        match = re.search(r"([0-9]{1,2}):([0-9]{2})", text)
        if not match:
            raise ValueError(text)
        return (int(match.group(1)) % 24) * 60 + int(match.group(2))

    @staticmethod
    def _content(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("content", ""))
        return str(item or "")

    def _rule_parse(self, text: str) -> dict[str, Any]:
        out = default_preferences()
        for cat in _CATEGORIES:
            if cat in text:
                around = self._window(text, cat)
                if re.search(r"不接|禁止|推掉|干不了|一律不接|扣钱|每接", around):
                    out["hard_ban_categories"].append(cat)
                elif re.search(r"尽量不|不太想|少接|少拉", around):
                    out["soft_avoid_categories"].append(cat)
        for region in _REGIONS:
            if region in text:
                around = self._window(text, region, 42)
                if re.search(r"不往|别.*进|禁止|不接|一律不接|不跑|不去", around):
                    out["forbidden_regions"].append({"region": region, "days": self._parse_days(around)})
                elif re.search(r"尽量|少去|不太想", around):
                    out["avoid_regions"].append({"region": region, "days": self._parse_days(around)})
        rest = re.search(r"连续(?:停.?车|休息|睡觉|熄火)?[^0-9一二三四五六七八九十]{0,8}([0-9一二三四五六七八九十]+)\s*(?:个)?小时", text)
        if rest:
            out["daily_rest"]["min_continuous_minutes"] = self._num(rest.group(1)) * 60
        if "零点" in text and "六点" in text:
            out["scheduled_rest_windows"].append({"start_minute": 0, "end_minute": 360})
        for a, b in re.findall(r"([0-9一二三四五六七八九十]{1,3})\s*[点:：]\s*(?:到|至|~|-)\s*([0-9一二三四五六七八九十]{1,3})\s*点?", text):
            start = self._num(a) % 24
            end = self._num(b) % 24
            out["scheduled_rest_windows"].append({"start_minute": start * 60, "end_minute": end * 60})
        off = re.search(r"(?:至少|起码|得)?\s*([0-9一二两三四五六七八九十]+)\s*个?整天", text)
        if off:
            out["monthly_off_days"] = self._num(off.group(1))
        pickup = re.search(r"(?:空驶|赶去装货|装货那一程)[^0-9一二三四五六七八九十]{0,12}(?:超过|不超(?:过)?|大于)?\s*([0-9一二三四五六七八九十]+)\s*公?里", text)
        if pickup:
            out["max_pickup_deadhead_km"] = float(self._num(pickup.group(1)))
        haul = re.search(r"(?:单笔|运输|装卸|干线)[^0-9一二三四五六七八九十]{0,12}(?:不超(?:过)?|超过)?\s*([0-9一二三四五六七八九十]+)\s*公?里", text)
        if haul:
            out["max_haul_km"] = float(self._num(haul.group(1)))
        for region in _REGIONS:
            around = self._window(text, region, 60)
            days = re.search(r"([0-9一二三四五六七八九十]+)\s*个?不同.*日|([0-9一二三四五六七八九十]+)\s*天", around)
            if days and re.search(r"起码|至少|接够|覆盖|装货|卸货", around):
                out["required_region_order_days"].append({"region": region, "min_days": self._num(days.group(1) or days.group(2))})
        out["required_location_stops"].extend(self._parse_location_stops(text))
        return self._dedupe(out)

    def _enhance_general_chinese(self, out: dict[str, Any], text: str) -> dict[str, Any]:
        if not text:
            return out
        known_before = self._known_constraint_count(out)
        categories = ["蔬菜", "机械设备", "化工塑料", "煤炭矿产", "鲜活水产品", "快递快运搬家", "食品饮料", "家具家居", "数码家电"]
        for cat in categories:
            if cat not in text:
                continue
            around = self._window(text, cat, 40)
            if re.search(r"(不接|不能接|禁止接|一律.*?(推掉|不接)|不拉|不跑|跳过|扣钱|不考虑)", around):
                out["hard_ban_categories"].append(cat)
            elif re.search(r"(尽量不接|能不接就不接|不太想|少接|少拉|优先不拉)", around):
                out["soft_avoid_categories"].append(cat)
        for match in re.finditer(r"(?:不接|不能接|禁止接|一律不接|不拉|不考虑)\s*([^，。；;\n]{1,12}?)(?:类货|货源|货物|类|，|。|；|;|$)", text):
            keyword = match.group(1).strip(" 的")
            if keyword and not any(x in keyword for x in ("单", "活", "订单", "长途", "短途")):
                out["hard_ban_categories"].append(keyword)
        regions = ["深圳", "广州", "佛山", "东莞", "惠州", "中山", "江门", "增城", "四会", "宝安", "龙岗", "白云", "黄埔", "南海", "顺德", "博罗"]
        for region in regions:
            if region not in text:
                continue
            around = self._window(text, region, 52)
            if re.search(r"(不去|不进|不跑|不往|禁止|一律.*?(不接|跳过)|起点.*不接|终点.*不接|装货地.*不接|卸货地.*不接|不进入)", around):
                out["forbidden_regions"].append({"region": region, "days": self._parse_arabic_days(around)})
            elif re.search(r"(尽量|少去|不太想|少跑)", around):
                out["avoid_regions"].append({"region": region, "days": self._parse_arabic_days(around)})
            if re.search(r"(只在|不能离开)", around):
                out.setdefault("allowed_regions", []).append(region)
        rest = re.search(r"(?:每天|每日).*?(?:连续|不间断|停车|休息|睡|熄火).*?([0-9一二两三四五六七八九十]+)\s*(?:个)?小时", text)
        if rest:
            out["daily_rest"]["min_continuous_minutes"] = max(int(out["daily_rest"].get("min_continuous_minutes") or 0), self._num_cn(rest.group(1)) * 60)
        for a, b in re.findall(r"([0-9]{1,2})(?::00)?\s*(?:点|:00)?\s*(?:到|至|-|~)\s*(?:次日)?\s*([0-9]{1,2})(?::00)?\s*(?:点|:00)?[^。；\n]*(?:不接|不空驶|不跑|休息|睡觉)", text):
            out["scheduled_rest_windows"].append({"start_minute": int(a) % 24 * 60, "end_minute": int(b) % 24 * 60})
        if "凌晨" in text and re.search(r"不跑|不接|休息", text):
            out["scheduled_rest_windows"].append({"start_minute": 2 * 60, "end_minute": 5 * 60})
        if "夜里" in text and re.search(r"不接|不跑", text):
            out["scheduled_rest_windows"].append({"start_minute": 22 * 60, "end_minute": 6 * 60})
        off = re.search(r"(?:每月|整个月|至少).*?([0-9一二两三四五六七八九十]+)\s*(?:天|个).*?(?:完整休息|不出车|不接单|不空驶|停车检修|在家不跑)", text)
        if off:
            out["monthly_off_days"] = max(int(out.get("monthly_off_days") or 0), self._num_cn(off.group(1)))
        pickup = re.search(r"(?:接货空驶|去装货地|装货地|赶装货).*?(?:不超过|超过|大于)\s*([0-9]+)\s*(?:km|公里)", text, re.I)
        if pickup:
            out["max_pickup_deadhead_km"] = float(pickup.group(1))
        haul = re.search(r"(?:装卸距离|单趟|单笔|干线|长途).*?(?:不超过|超过)\s*([0-9]+)\s*(?:km|公里)", text, re.I)
        if haul:
            out["max_haul_km"] = float(haul.group(1))
        if re.search(r"长途不接", text) and not out.get("max_haul_km"):
            out["max_haul_km"] = 180.0
        if re.search(r"(回家|到家|家里|指定坐标|停留|接人|再回|某日|必须.*?在家)", text):
            self._parse_generic_required_stop(out, text)
        self._parse_sequential_named_stops(out, text)
        self._parse_home_rule_strict(out, text)
        self._parse_date_region_bans_strict(out, text)
        self._parse_generic_hard_categories(out, text)
        self._mark_unlocated_required_stops(out, text)
        home_match = re.search(r"(?:每天|每日)?.*?([0-9]{1,2})\s*点\s*前(?:回家|到家)", text)
        if home_match or re.search(r"(回家|到家|家里)", text):
            deadline = (int(home_match.group(1)) % 24) * 60 if home_match else 22 * 60
            stay_match = re.search(r"(?:次日|早上)?\s*([0-9]{1,2})\s*点\s*前.*?(?:不跑|不接|不出车)", text)
            stay_until = (int(stay_match.group(1)) % 24) * 60 if stay_match else 8 * 60
            out["home_rules"].append(
                {
                    "deadline_minute": deadline,
                    "stay_until_minute": stay_until,
                    "home_location": None,
                    "home_location_source": "initial_position_or_explicit_coordinate",
                }
            )
        self._mark_unknown_risk(out, text, known_before)
        return self._dedupe(out)

    def _parse_generic_required_stop(self, out: dict[str, Any], text: str) -> None:
        chinese_numbers = {
            "一": 1,
            "两": 2,
            "二": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }
        for sentence in re.split(r"[。；;\n]", text):
            coord = re.search(r"([0-9]{2}\.[0-9]+)\s*[,，]\s*([0-9]{3}\.[0-9]+)", sentence)
            day_match = re.search(
                r"(?:2026\s*[-/年]\s*)?0?3\s*[-/月]\s*([0-9]{1,2})\s*(?:日|号)?",
                sentence,
            )
            if not coord or not day_match:
                continue
            hour_match = re.search(r"([0-9]{1,2})\s*(?:点|:00)\s*前", sentence)
            hour = int(hour_match.group(1)) % 24 if hour_match else 18
            stay = 60
            stay_match = re.search(r"停留\s*([0-9一两二三四五六七八九十]+)\s*(分钟|小时)", sentence)
            if stay_match:
                amount_text = stay_match.group(1)
                amount = int(amount_text) if amount_text.isdigit() else chinese_numbers.get(amount_text, 1)
                stay = amount * (60 if stay_match.group(2) == "小时" else 1)
            out["required_location_stops"].append(
                {
                    "day": int(day_match.group(1)),
                    "latitude": float(coord.group(1)),
                    "longitude": float(coord.group(2)),
                    "region": "",
                    "min_stop_minutes": stay,
                    "deadline_minute_of_day": hour * 60,
                    "earliest_minute_of_day": None,
                }
            )

    @staticmethod
    def _parse_home_rule_strict(out: dict[str, Any], text: str) -> None:
        for sentence in re.split(r"[。；;\n]", text):
            if "回家" not in sentence and "到家" not in sentence:
                continue
            deadline_match = re.search(r"([0-9]{1,2})\s*点\s*前[^。；;\n]*(?:回家|到家)", sentence)
            if not deadline_match:
                continue
            stay_match = re.search(
                r"(?:次日|第二天|翌日|早上|上午)[^。；;\n]*?([0-9]{1,2})\s*点\s*前[^。；;\n]*?"
                r"(?:不接|不跑|不出车|不空驶|不驾驶)",
                sentence,
            )
            out["home_rules"].append(
                {
                    "deadline_minute": int(deadline_match.group(1)) % 24 * 60,
                    "stay_until_minute": int(stay_match.group(1)) % 24 * 60 if stay_match else 8 * 60,
                    "home_location": None,
                    "home_location_source": "initial_position_or_explicit_coordinate",
                }
            )

    @staticmethod
    def _parse_sequential_named_stops(out: dict[str, Any], text: str) -> None:
        for sentence in re.split(r"[。；;\n]", text):
            if "先" not in sentence:
                continue
            day_match = re.search(r"(?:3月|三月)\s*([0-9]{1,2}|[一二两三四五六七八九十]{1,3})\s*(?:日|号)", sentence)
            if not day_match:
                continue
            day_text = day_match.group(1)
            day = int(day_text) if day_text.isdigit() else PreferenceParser._num_cn(day_text)
            coord_match = re.search(r"([0-9]{2}\.[0-9]+)\s*[,，]\s*([0-9]{3}\.[0-9]+)", sentence)
            if not coord_match:
                continue
            after_first = sentence[sentence.find("先") + 1 :]
            first_clause = re.split(
                r"[，,]?\s*(?:再|然后|接着|随后|赶到|再去|再到)",
                after_first,
                maxsplit=1,
            )[0]
            for region, coords in _REGION_COORDS.items():
                if region not in first_clause:
                    continue
                out["required_location_stops"].append(
                    {
                        "day": day,
                        "latitude": coords[0],
                        "longitude": coords[1],
                        "region": region,
                        "min_stop_minutes": 1,
                        "deadline_minute_of_day": 12 * 60,
                        "earliest_minute_of_day": None,
                        "sequence": 1,
                    }
                )
    @staticmethod
    def _parse_date_region_bans_strict(out: dict[str, Any], text: str) -> None:
        number_map = {
            "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
            "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13,
            "十四": 14, "十五": 15, "十六": 16, "十七": 17, "十八": 18, "十九": 19,
            "二十": 20, "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24,
            "二十五": 25, "二十六": 26, "二十七": 27, "二十八": 28, "二十九": 29,
            "三十": 30, "三十一": 31,
        }
        regions = (
            "深圳", "广州", "佛山", "东莞", "惠州", "中山", "江门", "增城", "四会",
            "宝安", "龙岗", "白云", "黄埔", "南海", "顺德",
        )
        negative = re.compile(r"不去|不进|不跑|不往|不能去|禁止|别给我派|不接")
        dated_regions: set[str] = set()
        global_regions: set[str] = set()
        for sentence in re.split(r"[。；;\n]", text):
            if not negative.search(sentence):
                continue
            days = [int(x) for x in re.findall(r"(?:3|03)\s*月\s*([0-9]{1,2})\s*(?:日|号)", sentence)]
            for word in re.findall(r"(?:三月)?([一二两三四五六七八九十]{1,3})号", sentence):
                if word in number_map:
                    days.append(number_map[word])
            days = sorted(set(day for day in days if 1 <= day <= 31))
            generic_regions = re.findall(
                r"(?:不能去|不去|不进|不往|禁止去|禁止进入|别给我派进|别给我派去)\s*"
                r"([\u4e00-\u9fff]{2,12}?)(?=[，。；,;\s]|$)",
                sentence,
            )
            for region in set(regions).union(generic_regions):
                if region in sentence:
                    if days:
                        dated_regions.add(region)
                        out["forbidden_regions"].append({"region": region, "days": days})
                    else:
                        global_regions.add(region)
        date_only_regions = dated_regions - global_regions
        if date_only_regions:
            out["forbidden_regions"] = [
                rule
                for rule in out.get("forbidden_regions") or []
                if not (
                    isinstance(rule, dict)
                    and rule.get("region") in date_only_regions
                    and not rule.get("days")
                )
            ]

    @staticmethod
    def _parse_generic_hard_categories(out: dict[str, Any], text: str) -> None:
        for sentence in re.split(r"[。；;\n]", text):
            match = re.search(r"(?:不接|禁止接|不能接)\s*([^。；;\n]{1,40})", sentence)
            if not match:
                continue
            phrase = re.split(r"(?:的货|货源|货物|订单|，|,)", match.group(1), maxsplit=1)[0]
            for category in re.split(r"[、和及与或/]", phrase):
                category = category.strip()
                if 1 < len(category) <= 12:
                    out["hard_ban_categories"].append(category)

    @staticmethod
    def _mark_unlocated_required_stops(out: dict[str, Any], text: str) -> None:
        for sentence in re.split(r"[。；;\n]", text):
            has_date = bool(re.search(r"(?:[0-9]{1,2}|三)\s*月\s*[0-9]{1,2}\s*(?:日|号)?", sentence))
            has_required_stop = bool(re.search(r"(?:必须|务必|一定)?.*?(?:到|去|抵达).*(?:停留|待|等到)", sentence))
            has_coord = bool(re.search(r"[0-9]{2}\.[0-9]+\s*[,，]\s*[0-9]{3}\.[0-9]+", sentence))
            if has_date and has_required_stop and not has_coord:
                known_place = next((name for name in _REGION_COORDS if name in sentence), None)
                if not known_place:
                    out["unknown_hard_constraints"].append(sentence.strip())
                    out["requires_conservative_mode"] = True

    def _mark_unknown_risk(self, out: dict[str, Any], text: str, known_before: int) -> None:
        keywords = ["必须", "禁止", "不准", "罚", "扣", "一定", "务必", "回家", "到家", "停留", "休息", "一律", "不能", "先到", "再回", "接人"]
        hits = [kw for kw in keywords if kw in text]
        out["high_risk_keywords"] = sorted(set((out.get("high_risk_keywords") or []) + hits))
        known_after = self._known_constraint_count(out)
        if hits and known_after <= known_before:
            snippets = [s.strip() for s in re.split(r"[。；;\n]", text) if any(kw in s for kw in hits)]
            out["unknown_hard_constraints"].extend(snippets[:3])
        out["requires_conservative_mode"] = bool(out.get("unknown_hard_constraints"))
        if out["requires_conservative_mode"]:
            out["parser_confidence"] = min(float(out.get("parser_confidence", 1.0)), 0.65)
        else:
            out["parser_confidence"] = max(float(out.get("parser_confidence", 0.0)), 0.9 if hits else 1.0)

    @staticmethod
    def _known_constraint_count(out: dict[str, Any]) -> int:
        count = 0
        for key in ("hard_ban_categories", "soft_avoid_categories", "scheduled_rest_windows", "required_region_order_days", "forbidden_regions", "avoid_regions", "required_location_stops"):
            count += len(out.get(key) or [])
        for key in ("monthly_off_days", "max_pickup_deadhead_km", "max_haul_km"):
            count += 1 if out.get(key) else 0
        count += 1 if (out.get("daily_rest") or {}).get("min_continuous_minutes") else 0
        return count

    @staticmethod
    def _parse_arabic_days(text: str) -> list[int] | None:
        days = [int(x) for x in re.findall(r"3\s*月\s*([0-9]{1,2})\s*(?:日|号)", text)]
        return days or None

    @staticmethod
    def _num_cn(text: str) -> int:
        text = str(text)
        if text.isdigit():
            return int(text)
        values = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        if text == "十":
            return 10
        if "十" in text:
            left, _, right = text.partition("十")
            return (values.get(left, 1) * 10) + values.get(right, 0)
        return values.get(text, 0)

    def _needs_llm(self, parsed: dict[str, Any], text: str) -> bool:
        if not self._params.enable_llm_preference_parser:
            return False
        if not text.strip():
            return False
        if self._params.force_llm_when_preferences_exist:
            return True
        if float(parsed.get("parser_confidence", 0.0)) >= 0.9 and not parsed.get("unknown_hard_constraints"):
            return False
        return True
        signals = ["坐标", "先到", "再到", "停留", "查车", "交警", "自然月"]
        has_signal = any(s in text for s in signals)
        known = sum(len(parsed[k]) for k in ("hard_ban_categories", "forbidden_regions", "scheduled_rest_windows", "required_region_order_days"))
        return has_signal and known < 2

    def _merge_llm_safely(self, base: dict[str, Any], raw_extra: dict[str, Any]) -> dict[str, Any]:
        out = deepcopy(base)
        extra_seed = default_preferences()
        for key, value in raw_extra.items():
            if key in extra_seed:
                extra_seed[key] = value
        extra = self._normalize_llm_schema(extra_seed)

        list_keys = (
            "hard_ban_categories",
            "soft_avoid_categories",
            "scheduled_rest_windows",
            "required_region_order_days",
            "avoid_regions",
            "required_location_stops",
            "home_rules",
            "unknown_soft_constraints",
        )
        for key in list_keys:
            out.setdefault(key, []).extend(extra.get(key) or [])
        base_confidence = float(out.get("parser_confidence", 0.0) or 0.0)
        accept_llm_unknown = bool(out.get("unknown_hard_constraints")) or base_confidence < 0.85
        if accept_llm_unknown:
            out.setdefault("unknown_hard_constraints", []).extend(extra.get("unknown_hard_constraints") or [])
        base_global_regions = {
            str(rule.get("region"))
            for rule in out.get("forbidden_regions") or []
            if isinstance(rule, dict) and rule.get("region") and not rule.get("days")
        }
        base_dated_regions = {
            str(rule.get("region"))
            for rule in out.get("forbidden_regions") or []
            if isinstance(rule, dict) and rule.get("region") and rule.get("days")
        }
        for rule in extra.get("forbidden_regions") or []:
            region = str(rule.get("region")) if isinstance(rule, dict) and rule.get("region") else ""
            days = rule.get("days") if isinstance(rule, dict) else None
            if region and not days and region in base_dated_regions and region not in base_global_regions:
                continue
            out.setdefault("forbidden_regions", []).append(rule)
        out["home_rules"] = [
            rule
            for rule in out["home_rules"]
            if isinstance(rule, dict)
            and isinstance(rule.get("deadline_minute"), (int, float))
            and int(rule["deadline_minute"]) != int(rule.get("stay_until_minute", -1))
        ]

        base_rest = int((out.get("daily_rest") or {}).get("min_continuous_minutes") or 0)
        extra_rest = int((extra.get("daily_rest") or {}).get("min_continuous_minutes") or 0)
        out.setdefault("daily_rest", {})["min_continuous_minutes"] = max(base_rest, extra_rest) or None

        for key in ("max_pickup_deadhead_km", "max_haul_km"):
            values = [
                float(value)
                for value in (out.get(key), extra.get(key))
                if isinstance(value, (int, float)) and float(value) > 0
            ]
            out[key] = min(values) if values else None
        off_days = [
            int(value)
            for value in (out.get("monthly_off_days"), extra.get("monthly_off_days"))
            if isinstance(value, (int, float)) and int(value) > 0
        ]
        out["monthly_off_days"] = max(off_days) if off_days else None

        base_allowed = {str(x) for x in out.get("allowed_regions") or [] if x}
        extra_allowed = {str(x) for x in extra.get("allowed_regions") or [] if x}
        if base_allowed and extra_allowed and base_allowed.isdisjoint(extra_allowed):
            out["unknown_hard_constraints"].append("conflicting_allowed_regions")
        out["allowed_regions"] = sorted(base_allowed | extra_allowed)

        llm_unknown = accept_llm_unknown and bool(extra.get("unknown_hard_constraints"))
        llm_conservative = bool(extra.get("requires_conservative_mode"))
        out["requires_conservative_mode"] = bool(
            out.get("requires_conservative_mode")
            or llm_conservative
            or llm_unknown
            or (self._params.unknown_preference_conservative and out.get("high_risk_keywords"))
        )
        confidences = [
            float(value)
            for value in (out.get("parser_confidence"), extra.get("parser_confidence"))
            if isinstance(value, (int, float))
        ]
        out["parser_confidence"] = min(confidences) if confidences else 0.0
        if out["requires_conservative_mode"]:
            out["parser_confidence"] = min(out["parser_confidence"], 0.65)
        return self._dedupe(out)

    def _finalize_safety(self, parsed: dict[str, Any]) -> dict[str, Any]:
        parsed["scheduled_rest_windows"] = [
            win
            for win in parsed.get("scheduled_rest_windows") or []
            if isinstance(win, dict)
            and isinstance(win.get("start_minute"), (int, float))
            and isinstance(win.get("end_minute"), (int, float))
            and int(win["start_minute"]) != int(win["end_minute"])
        ]
        parsed["home_rules"] = [
            rule
            for rule in parsed.get("home_rules") or []
            if isinstance(rule, dict)
            and isinstance(rule.get("deadline_minute"), (int, float))
            and int(rule["deadline_minute"]) != int(rule.get("stay_until_minute", -1))
        ]
        if parsed.get("unknown_hard_constraints"):
            parsed["requires_conservative_mode"] = True
            parsed["parser_confidence"] = min(float(parsed.get("parser_confidence", 1.0)), 0.65)
        parsed["required_location_stops"] = sorted(
            parsed.get("required_location_stops") or [],
            key=lambda stop: (int(stop.get("day", 99)), int(stop.get("sequence", 2))),
        )
        return self._dedupe(parsed)

    @staticmethod
    def _dedupe(data: dict[str, Any]) -> dict[str, Any]:
        for key in ("hard_ban_categories", "soft_avoid_categories"):
            data[key] = sorted(set(data[key]))
        for key in (
            "forbidden_regions",
            "avoid_regions",
            "required_region_order_days",
            "required_location_stops",
            "home_rules",
            "scheduled_rest_windows",
        ):
            seen = set()
            uniq = []
            for item in data[key]:
                sig = str(sorted(item.items())) if isinstance(item, dict) else str(item)
                if sig not in seen:
                    seen.add(sig)
                    uniq.append(item)
            data[key] = uniq
        return data

    @staticmethod
    def _window(text: str, needle: str, radius: int = 24) -> str:
        idx = text.find(needle)
        if idx < 0:
            return ""
        return text[max(0, idx - radius) : idx + len(needle) + radius]

    @staticmethod
    def _parse_days(text: str) -> list[int] | None:
        days = [int(x) for x in re.findall(r"3月([0-9]{1,2})|三月([0-9]{1,2})", text) for x in x if x]
        word_map = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}
        for word in re.findall(r"三月([一二两三四五六七八九十]{1,2})号", text):
            if word in word_map:
                days.append(word_map[word])
        compact = re.search(r"三月([一二两三四五六七八九十]{1,2})号([一二两三四五六七八九十]{1,2})号", text)
        if compact:
            for word in compact.groups():
                if word in word_map:
                    days.append(word_map[word])
        return days or None

    def _parse_location_stops(self, text: str) -> list[dict[str, Any]]:
        stops: list[dict[str, Any]] = []
        day_words = {
            "一": 1,
            "二": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
            "十一": 11,
            "十二": 12,
            "三十一": 31,
        }
        for sentence in re.split(r"[。；;\n]", text):
            match = re.search(r"三月([一二三四五六七八九十]{1,3}|[0-9]{1,2})号", sentence)
            if not match:
                continue
            day = int(match.group(1)) if match.group(1).isdigit() else day_words.get(match.group(1), 0)
            around = sentence[match.start() :]
            if not day or not re.search(r"停|到|赶到|过", around):
                continue
            lat_lng = re.search(r"([0-9]{2}\.[0-9]+)\s*[，,]\s*([0-9]{3}\.[0-9]+)", around)
            lat = lng = None
            region = ""
            if lat_lng:
                lat, lng = float(lat_lng.group(1)), float(lat_lng.group(2))
            else:
                for name, coords in _REGION_COORDS.items():
                    if name in around:
                        region = name
                        lat, lng = coords
                        break
            if lat is None or lng is None:
                continue
            min_stop = 120 if re.search(r"两小时|2小时|下午两点|下午2点", around) else 60
            deadline = 12 * 60 if re.search(r"中午|十二点|12点", around) else 18 * 60
            earliest = 12 * 60 if re.search(r"中午|十二点|12点", around) else None
            stops.append(
                {
                    "day": day,
                    "latitude": lat,
                    "longitude": lng,
                    "region": region,
                    "min_stop_minutes": min_stop,
                    "deadline_minute_of_day": deadline,
                    "earliest_minute_of_day": earliest,
                }
            )
        return stops

    @staticmethod
    def _num(text: str) -> int:
        text = str(text)
        if text.isdigit():
            return int(text)
        values = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        if text == "十":
            return 10
        if "十" in text:
            left, _, right = text.partition("十")
            return (values.get(left, 1) * 10) + values.get(right, 0)
        return values.get(text, 0)
