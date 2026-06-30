from __future__ import annotations

from typing import Any

from .config import StrategyParams


def validate_action(
    action: dict[str, Any],
    allowed_cargo_ids: set[str],
    status: dict[str, Any],
    preferences: dict[str, Any],
    params: StrategyParams,
) -> dict[str, Any]:
    try:
        name = str(action.get("action", "")).strip().lower()
        body = action.get("params")
        if not isinstance(body, dict):
            raise ValueError("params_not_object")
        if name == "take_order":
            cargo_id = str(body.get("cargo_id", "")).strip()
            if not cargo_id or (allowed_cargo_ids and cargo_id not in allowed_cargo_ids):
                raise ValueError("cargo_not_allowed")
            return {"action": "take_order", "params": {"cargo_id": cargo_id}}
        if name == "reposition":
            lat, lng = float(body["latitude"]), float(body["longitude"])
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise ValueError("bad_coordinate")
            return {"action": "reposition", "params": {"latitude": lat, "longitude": lng}}
        if name == "wait":
            duration = int(body.get("duration_minutes", 0))
            if duration <= 0:
                raise ValueError("bad_wait")
            return {"action": "wait", "params": {"duration_minutes": min(duration, 24 * 60)}}
    except Exception:
        pass
    return {"action": "wait", "params": {"duration_minutes": max(1, int(params.fallback_wait_minutes))}}
