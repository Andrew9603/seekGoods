from __future__ import annotations

from typing import Any


class RiskClassifier:
    def classify(self, preferences: dict[str, Any]) -> str:
        if not preferences.get("_raw_text_present"):
            return "no_pref_or_low_risk"
        confidence = float(preferences.get("parser_confidence", 0.0) or 0.0)
        forbidden = preferences.get("forbidden_regions") or []
        has_date_region_ban = bool(preferences.get("date_region_bans")) or any(
            isinstance(rule, dict) and rule.get("days") for rule in forbidden
        )
        structured_high = any(
            [
                preferences.get("home_rules"),
                preferences.get("required_location_stops"),
                has_date_region_ban,
                preferences.get("monthly_off_days"),
                preferences.get("allowed_regions"),
                preferences.get("only_regions"),
            ]
        )
        unknown = bool(preferences.get("unknown_hard_constraints"))
        llm_failed_with_unresolved_hard_text = bool(
            preferences.get("_llm_parse_failed") and preferences.get("requires_conservative_mode")
        )
        if unknown or llm_failed_with_unresolved_hard_text or confidence < 0.75:
            return "unknown_high_risk"
        if structured_high:
            return "structured_high_risk"
        medium = any(
            [
                (preferences.get("daily_rest") or {}).get("min_continuous_minutes")
                and not preferences.get("_default_daily_rest_applied"),
                [
                    win
                    for win in preferences.get("scheduled_rest_windows") or []
                    if win.get("source") != "submission_safe_default"
                ],
                forbidden,
            ]
        )
        if medium and confidence >= 0.8:
            return "structured_medium_risk"
        return "structured_high_risk" if medium else "no_pref_or_low_risk"
