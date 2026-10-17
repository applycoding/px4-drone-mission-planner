import asyncio

import pytest

from mission_planner.controller import MissionController, mavsdk_battery_percent
from mission_planner.energy import EnergyModel
from mission_planner.fake_system import FakeSystem
from mission_planner.geometry import xy_to_latlon
from mission_planner.mission import VehicleAction

from tests.support import ORIGIN, square_spec

ADDRESS = "udpin://0.0.0.0:14540"
HAPPY_EVENTS = [
    "connect",
    "connection_state",
    "health",
    "home",
    "battery",
    "set_return_to_launch_after_mission",
    "upload_geofence",
    "upload_mission",
    "arm",
    "start_mission",
]


def _model() -> EnergyModel:
    return EnergyModel(
        capacity_wh=100,
        wh_per_km=20,
        min_start_percent=30,
        landing_reserve_percent=20,
        rth_safety_factor=1.2,
    )


def _ready(
    battery: float = 0.95,
    *,
    connected: bool = True,
    timeout_s: float = 15.0,
    spec=None,
):
    spec = spec or square_spec()
    system = FakeSystem(connected=connected, battery_fraction=battery)
    system.set_home(spec.home.lat, spec.home.lon)
    controller = MissionController(system, address=ADDRESS, timeout_s=timeout_s)
    return system, controller, spec


def test_mavsdk_battery_fraction_scales_to_percent() -> None:
    assert mavsdk_battery_percent(0.82) == pytest.approx(82)
    assert mavsdk_battery_percent(1) == pytest.approx(100)
    assert mavsdk_battery_percent(0) == pytest.approx(0)
    with pytest.raises(ValueError):
        mavsdk_battery_percent(80)
    with pytest.raises(ValueError):
        mavsdk_battery_percent(-0.1)
    with pytest.raises(ValueError):
        mavsdk_battery_percent(float("nan"))


def test_launch_uploads_then_arms_then_starts() -> None:
    system, controller, _spec = _ready()
    result = asyncio.run(controller.launch(square_spec(), _model()))
    assert result.started is True
    assert result.stage == "started"
    assert system.events == HAPPY_EVENTS
    assert system.connected_address == ADDRESS
    assert system.mission.rtl_after_mission is True
    assert system.action.armed is True
    assert system.mission.started is True
    uploaded = system.mission.uploaded
    assert uploaded is result.mission
    assert uploaded.waypoints[0].vehicle_action is VehicleAction.TAKEOFF
    assert len(system.geofence.uploaded) == 4
    assert result.energy is not None and result.energy.allowed is True
    assert result.remaining_percent == pytest.approx(95)


def test_low_battery_does_not_arm_or_upload() -> None:
    system, controller, spec = _ready(battery=0.2)
    result = asyncio.run(controller.launch(spec, _model()))
    assert result.started is False
    assert result.stage == "rejected"
    assert "start minimum" in result.reason
    assert system.action.armed is False
    assert system.mission.uploaded is None
    assert system.mission.rtl_after_mission is None
    assert "arm" not in system.events
    assert "upload_mission" not in system.events


def test_home_outside_the_fence_does_not_arm() -> None:
    spec = square_spec()
    system, controller, _spec = _ready()
    outside = xy_to_latlon(-50, 50, ORIGIN)
    system.set_home(outside.lat, outside.lon)
    result = asyncio.run(controller.launch(spec, _model()))
    assert result.started is False
    assert "outside" in result.reason
    assert system.action.armed is False
    assert "upload_mission" not in system.events


def test_failed_upload_does_not_arm() -> None:
    system, controller, spec = _ready()
    system.mission.fail_upload = True
    result = asyncio.run(controller.launch(spec, _model()))
    assert result.started is False
    assert result.stage == "rejected"
    assert "upload failed" in result.reason
    assert system.action.armed is False
    assert system.mission.started is False
    assert system.events[-1] == "upload_mission"


def test_failed_geofence_upload_skips_the_mission() -> None:
    system, controller, spec = _ready()
    system.geofence.fail = True
    result = asyncio.run(controller.launch(spec, _model()))
    assert "geofence rejected" in result.reason
    assert system.mission.uploaded is None
    assert system.action.armed is False
    assert "upload_mission" not in system.events


def test_failed_arm_does_not_start() -> None:
    system, controller, spec = _ready()
    system.action.fail_arm = True
    result = asyncio.run(controller.launch(spec, _model()))
    assert result.started is False
    assert result.stage == "uploaded"
    assert "arm failed" in result.reason
    assert system.mission.uploaded is not None
    assert system.mission.started is False


def test_unhealthy_vehicle_is_not_armed() -> None:
    system, controller, spec = _ready()
    system.telemetry.health_reading.is_global_position_ok = False
    result = asyncio.run(controller.launch(spec, _model()))
    assert result.started is False
    assert "armable" in result.reason
    assert system.action.armed is False
    assert "battery" not in system.events


def test_health_timeout_does_not_hang() -> None:
    system, controller, spec = _ready(timeout_s=0.1)
    system.telemetry.health_reading.is_armable = False
    system.telemetry.health_delay_s = 5
    result = asyncio.run(controller.launch(spec, _model()))
    assert result.started is False
    assert "timed out" in result.reason
    assert system.action.armed is False


def test_disconnected_vehicle_is_rejected() -> None:
    system, controller, spec = _ready(connected=False)
    result = asyncio.run(controller.launch(spec, _model()))
    assert result.started is False
    assert "did not connect" in result.reason
    assert "health" not in system.events


def test_in_flight_reserve_commands_rtl_at_the_threshold() -> None:
    system, controller, _spec = _ready(battery=0.2)
    action = asyncio.run(controller.enforce_rth_reserve(_model()))
    assert action.action == "rtl"
    assert action.remaining_percent == pytest.approx(20)
    assert system.action.rtl_called is True

    system.set_battery_fraction(0.5)
    action = asyncio.run(controller.enforce_rth_reserve(_model()))
    assert action.action == "continue"
    assert system.events[-1] == "battery"
