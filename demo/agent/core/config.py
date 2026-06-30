from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StrategyParams:
    profile_name: str = "robust_mpc_adaptive"
    enable_llm_preference_parser: bool = True
    force_llm_when_preferences_exist: bool = False
    llm_preference_model_name: str = "qwen3.5-flash"
    llm_parse_timeout_seconds: float = 5.0
    llm_preference_max_tokens: int = 1400
    llm_max_calls_per_driver: int = 2
    soft_decision_timeout_ms: int = 2000
    query_k_low: int = 50
    query_k_default: int = 100
    query_k_peak: int = 150
    query_k_max: int = 200
    reposition_speed_km_per_hour: float = 60.0
    cost_per_km_default: float = 1.5
    profit_weight: float = 1.0
    profit_per_hour_weight: float = 80.0
    destination_weight: float = 100.0
    pickup_deadhead_penalty: float = 1.5
    wait_minutes_penalty: float = 0.2
    soft_category_penalty: float = 500.0
    forbidden_window_penalty: float = 10000.0
    allow_preference_tradeoff: bool = False
    unknown_preference_conservative: bool = False
    hard_preference_filter_first: bool = False
    strict_time_window_overlap_check: bool = False
    strict_region_constraint: bool = False
    strict_daily_rest: bool = False
    strict_monthly_off_days: bool = False
    strict_required_stop: bool = False
    strict_home_rule: bool = False
    strict_date_region_ban: bool = False
    strict_category_filter: bool = False
    strict_distance_limit: bool = False
    default_night_rest_if_preferences_exist: bool = False
    default_night_rest_start_hour: int = 22
    default_night_rest_end_hour: int = 8
    default_daily_rest_minutes_if_preferences_exist: int | None = 0
    avoid_cross_day_orders_if_preferences_exist: bool = False
    avoid_night_finish_if_preferences_exist: bool = False
    evening_cutoff_hour: int = 20
    max_evening_order_duration_minutes: int = 240
    max_order_duration_minutes_when_constraints_exist: int = 480
    max_pickup_deadhead_km_when_constraints_exist: float = 60.0
    max_linehaul_km_when_constraints_exist: float = 220.0
    prefer_short_orders_when_constraints_exist: bool = False
    prefer_short_orders_when_unknown_constraints_exist: bool = False
    max_order_duration_minutes_when_unknown_constraints_exist: int = 300
    max_pickup_deadhead_km_when_unknown_constraints_exist: float = 40.0
    max_linehaul_km_when_unknown_constraints_exist: float = 150.0
    avoid_cross_day_long_orders_when_constraints_exist: bool = False
    conservative_min_order_score: float = 140.0
    conservative_max_pickup_km: float = 35.0
    conservative_max_haul_km: float = 180.0
    conservative_night_wait_start_minute: int = 22 * 60
    penalty_safety_multiplier: float = 1.3
    max_acceptable_preference_penalty_per_rule: float = 5000.0
    finish_daytime_bonus: float = 80.0
    finish_peak_bonus: float = 120.0
    finish_late_rest_penalty: float = 180.0
    endgame_destination_weight_multiplier: float = 0.6
    endgame_profit_per_hour_multiplier: float = 1.35
    endgame_long_order_penalty: float = 120.0
    endgame_pickup_penalty_multiplier: float = 1.4
    endgame_remaining_days: int = 3
    min_order_score: float = 30.0
    max_reposition_km: float = 80.0
    reposition_score_threshold: float = 150.0
    fallback_wait_minutes: int = 60
    enable_mpc_planner: bool = False
    mpc_top_k: int = 30
    future_value_weight: float = 180.0
    soft_preference_lambda: float = 1.0
    unknown_risk_lambda: float = 8.0
    deadline_safety_margin: int = 180
    enable_adaptive_mode: bool = False
    slack_risk_penalty_weight: float = 4.0
    query_cost_penalty_weight: float = 1.0


def load_strategy_params(path: Path | None = None) -> StrategyParams:
    config_dir = Path(__file__).resolve().parents[1] / "config"
    path = path or config_dir / "strategy_params.json"
    raw = {}
    if path.is_file():
        raw.update(json.loads(path.read_text(encoding="utf-8")))
    profile_name = os.environ.get("AGENT_PROFILE", os.environ.get("AGENT_STRATEGY_PROFILE", "")).strip() or "robust_mpc_adaptive"
    profile_path = Path(os.environ.get("AGENT_STRATEGY_PROFILES_PATH", str(config_dir / "strategy_profiles.json")))
    if profile_name and profile_path.is_file():
        profiles = json.loads(profile_path.read_text(encoding="utf-8"))
        profile = profiles.get(profile_name)
        if isinstance(profile, dict):
            overrides = profile.get("overrides", profile)
            if isinstance(overrides, dict):
                raw.update(overrides)
            raw["profile_name"] = profile_name
    fields = StrategyParams.__dataclass_fields__
    return StrategyParams(**{k: v for k, v in raw.items() if k in fields})
