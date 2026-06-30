from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class AgentDebugLogger:
    def __init__(self) -> None:
        self._dir = Path(__file__).resolve().parents[2] / "results" / "agent_debug"

    def write(self, driver_id: str, payload: dict[str, Any]) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            data = dict(payload)
            data["wall_time"] = datetime.now().isoformat(timespec="seconds")
            path = self._dir / f"{driver_id}.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(data, ensure_ascii=False, default=str))
                fh.write("\n")
        except Exception:
            return
