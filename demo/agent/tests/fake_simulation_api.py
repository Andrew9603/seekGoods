from __future__ import annotations

from typing import Any


class FakeSimulationApi:
    def __init__(self, *, status: dict[str, Any] | None = None, items: list[dict[str, Any]] | None = None, llm_error: Exception | None = None) -> None:
        self.status = status or {
            "driver_id": "DTEST",
            "truck_length": "4.2米",
            "cost_per_km": 1.5,
            "current_lat": 23.0,
            "current_lng": 113.7,
            "simulation_progress_minutes": 8 * 60,
            "preferences": [],
        }
        self.items = items or []
        self.llm_error = llm_error

    def get_driver_status(self, driver_id: str) -> dict[str, Any]:
        return dict(self.status, driver_id=driver_id)

    def query_cargo(self, driver_id: str, latitude: float, longitude: float, k: int = 100) -> dict[str, Any]:
        return {"driver_id": driver_id, "k": k, "items": list(self.items)}

    def query_decision_history(self, driver_id: str, step: int) -> dict[str, Any]:
        return {"driver_id": driver_id, "records": [], "total_steps": 0, "returned_count": 0}

    def model_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.llm_error:
            raise self.llm_error
        return {"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 1}}
