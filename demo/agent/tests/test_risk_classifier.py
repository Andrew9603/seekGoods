from __future__ import annotations

from agent.core.risk_classifier import RiskClassifier


def test_risk_classifier_uses_preference_content() -> None:
    classifier = RiskClassifier()
    assert classifier.classify({"_raw_text_present": False}) == "no_pref_or_low_risk"
    assert classifier.classify(
        {
            "_raw_text_present": True,
            "hard_ban_categories": ["玻璃"],
            "parser_confidence": 1.0,
        }
    ) == "no_pref_or_low_risk"
    assert classifier.classify(
        {
            "_raw_text_present": True,
            "scheduled_rest_windows": [{"start_minute": 0, "end_minute": 360}],
            "parser_confidence": 0.95,
        }
    ) == "structured_medium_risk"
    assert classifier.classify(
        {
            "_raw_text_present": True,
            "required_location_stops": [{"day": 18}],
            "parser_confidence": 0.95,
        }
    ) == "structured_high_risk"
    assert classifier.classify(
        {
            "_raw_text_present": True,
            "unknown_hard_constraints": ["必须到某地"],
            "parser_confidence": 0.65,
        }
    ) == "unknown_high_risk"
