import pytest

from mission_planner.energy import (
    DEFAULT_CAPACITY_WH,
    DEFAULT_WH_PER_KM,
    PLACEHOLDER_NOTE,
    EnergyModel,
    evaluate_energy,
    evaluate_path,
)
from mission_planner.geometry import LatLon, xy_to_latlon


def _model(**overrides: float) -> EnergyModel:
    values = {
        "capacity_wh": 100.0,
        "wh_per_km": 10.0,
        "min_start_percent": 30.0,
        "landing_reserve_percent": 20.0,
        "rth_safety_factor": 1.0,
    }
    values.update(overrides)
    return EnergyModel(**values)


def test_defaults_are_placeholders() -> None:
    model = EnergyModel()
    assert model.placeholder is True
    assert model.capacity_wh == DEFAULT_CAPACITY_WH
    assert model.wh_per_km == DEFAULT_WH_PER_KM
    assert "not" in PLACEHOLDER_NOTE.lower()
    decision = evaluate_energy(0, 0, 100, model)
    assert decision.placeholder is True


def test_start_minimum_blocks_before_the_distance_budget() -> None:
    decision = evaluate_energy(0, 0, 25, _model())
    assert decision.allowed is False
    assert "start minimum" in decision.reason
    assert decision.available_wh == pytest.approx(25)


def test_return_from_the_farthest_waypoint_is_reserved() -> None:
    decision = evaluate_energy(100, 9000, 100, _model())
    assert decision.mission_wh == pytest.approx(1)
    assert decision.rth_wh == pytest.approx(90)
    assert decision.reserve_wh == pytest.approx(20)
    assert decision.required_wh == pytest.approx(111)
    assert decision.available_wh == pytest.approx(100)
    assert decision.allowed is False
    assert "farthest" in decision.reason


def test_short_mission_is_allowed() -> None:
    decision = evaluate_energy(100, 50, 100, _model())
    # 1 Wh survey + 0.5 Wh return + 20 Wh reserve.
    assert decision.required_wh == pytest.approx(21.5)
    assert decision.allowed is True
    assert "return-to-home" in decision.reason


def test_path_reserve_uses_the_far_point_not_the_endpoint() -> None:
    home = LatLon(0.0, 0.0)
    far = xy_to_latlon(0, 9000, home)
    end = xy_to_latlon(0, 10, home)
    model = EnergyModel(
        capacity_wh=10_000,
        wh_per_km=10,
        min_start_percent=0,
        landing_reserve_percent=0,
        rth_safety_factor=1,
    )
    decision = evaluate_path([home, far, end], home, 100, model)
    assert decision.farthest_home_m == pytest.approx(9000, abs=1)
    assert decision.rth_wh == pytest.approx(90, abs=0.1)
    assert decision.allowed is True


def test_rejects_nonsense_inputs() -> None:
    with pytest.raises(ValueError, match="remaining percent"):
        evaluate_energy(0, 0, 140, _model())
    with pytest.raises(ValueError, match="positive"):
        evaluate_energy(0, 0, 50, _model(capacity_wh=0))
    with pytest.raises(ValueError, match="rth_safety_factor"):
        evaluate_energy(0, 0, 50, _model(rth_safety_factor=0.5))
