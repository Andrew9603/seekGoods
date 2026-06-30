from __future__ import annotations

import json

from agent.core.cargo_filter import CargoFilter
from agent.core.cargo_prior import CargoPrior
from agent.core.config import StrategyParams

from .fake_simulation_api import FakeSimulationApi
from .test_agent_policy import cargo


def test_missing_cargo_prior_uses_defaults(tmp_path) -> None:
    prior = CargoPrior(tmp_path / "missing.json")
    assert prior.recommended_query_k(10, 177) == 177
    assert prior.score_bonus(10, "X", "Y") == 0.0


def test_cargo_prior_contains_only_aggregates() -> None:
    path = __import__("pathlib").Path(__file__).resolve().parents[1] / "config" / "cargo_prior.json"
    if not path.exists():
        return
    source = path.read_text(encoding="utf-8")
    assert "cargo_id" not in source
    data = json.loads(source)
    assert set(data) == {
        "schema_version",
        "record_count",
        "hour_prior",
        "region_prior",
        "destination_prior",
        "category_prior",
        "query_k_prior",
    }


def test_cargo_prior_cannot_bypass_firewall() -> None:
    item = cargo("blocked", name="玻璃")
    preferences = {"hard_ban_categories": ["玻璃"], "forbidden_regions": []}
    assert CargoFilter(StrategyParams()).filter_items(FakeSimulationApi().status, [item], preferences) == []
