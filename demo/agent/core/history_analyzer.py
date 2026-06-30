from __future__ import annotations

from typing import Any

from .time_utils import day_index


class HistoryAnalyzer:
    def analyze(self, history_resp: dict[str, Any], current_minute: int) -> dict[str, Any]:
        records = history_resp.get("records") if isinstance(history_resp, dict) else []
        if not isinstance(records, list):
            records = []
        today = day_index(current_minute)
        longest_wait_today = 0
        current_wait = 0
        active_days: set[int] = set()
        stopped_grids: dict[int, set[str]] = {}
        region_days: dict[str, set[int]] = {}
        recent_empty_or_wait_steps = 0
        last_action = None
        for rec in records:
            action = (rec.get("action") or {}).get("action") if isinstance(rec, dict) else None
            last_action = action or last_action
            end_min = self._extract_end_minute(rec)
            start_min = self._extract_start_minute(rec, end_min)
            rec_day = day_index(end_min)
            if action in {"take_order", "reposition"}:
                active_days.add(rec_day)
                current_wait = 0
            elif action == "wait" and rec_day == today:
                duration = int(((rec.get("action") or {}).get("params") or {}).get("duration_minutes", 0))
                current_wait += max(0, duration)
                longest_wait_today = max(longest_wait_today, current_wait)
                pos = rec.get("position_before") if isinstance(rec, dict) else None
                if isinstance(pos, dict) and duration >= 1 and start_min >= rec_day * 1440:
                    stopped_grids.setdefault(rec_day, set()).add(self._grid(pos.get("lat"), pos.get("lng"), precision=2))
            if action == "take_order":
                for key in ("position_after", "position_before"):
                    pos = rec.get(key) if isinstance(rec, dict) else None
                    if isinstance(pos, dict):
                        region_days.setdefault(self._grid(pos.get("lat"), pos.get("lng")), set()).add(rec_day)
        for rec in reversed(records[-5:]):
            action = ((rec.get("action") or {}).get("action") if isinstance(rec, dict) else None) or ""
            if action in {"wait", "reposition"}:
                recent_empty_or_wait_steps += 1
            else:
                break
        return {
            "records_count": len(records),
            "last_action": last_action,
            "longest_wait_today": longest_wait_today,
            "active_days": active_days,
            "monthly_off_days_done": self._completed_off_days(current_minute, active_days),
            "region_days": {k: len(v) for k, v in region_days.items()},
            "stopped_grids": {k: list(v) for k, v in stopped_grids.items()},
            "recent_empty_or_wait_steps": recent_empty_or_wait_steps,
        }

    @staticmethod
    def _extract_end_minute(rec: dict[str, Any]) -> int:
        try:
            return int(((rec.get("result") or {}).get("simulation_progress_minutes")))
        except Exception:
            return 0

    @staticmethod
    def _extract_start_minute(rec: dict[str, Any], end_minute: int) -> int:
        try:
            return int(end_minute) - int(rec.get("step_elapsed_minutes", 0))
        except Exception:
            return int(end_minute)

    @staticmethod
    def _grid(lat: Any, lng: Any, precision: int = 1) -> str:
        try:
            return f"{round(float(lat), precision)},{round(float(lng), precision)}"
        except Exception:
            return "unknown"

    @staticmethod
    def _completed_off_days(current_minute: int, active_days: set[int]) -> int:
        completed_days = current_minute // 1440
        return sum(1 for d in range(completed_days) if d not in active_days)
