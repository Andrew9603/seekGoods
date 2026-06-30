from __future__ import annotations

from agent.core.region_value import RegionValueModel


def test_dynamic_region_memory_is_isolated_by_driver() -> None:
    model = RegionValueModel()
    items = [
        {
            "cargo": {
                "price": 50000,
                "start": {"lat": 30.01, "lng": 120.01},
                "end": {"lat": 30.02, "lng": 120.02},
            }
        }
    ]
    model.observe_items("DRIVER_A", items)
    a_value = model.destination_value("DRIVER_A", 30.02, 120.02, {})
    b_value = model.destination_value("DRIVER_B", 30.02, 120.02, {})
    assert a_value > b_value
    assert "DRIVER_A" in model._seen
    assert "DRIVER_B" not in model._seen
