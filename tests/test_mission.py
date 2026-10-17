import pytest

from mission_planner.fields import px4_sample_field
from mission_planner.geofence import point_inside
from mission_planner.geometry import path_length_m, xy_to_latlon
from mission_planner.mission import VehicleAction, plan_survey

from tests.support import ORIGIN, square_spec


def test_mission_starts_with_takeoff_at_home() -> None:
    spec = square_spec()
    result = plan_survey(spec)
    assert result.ok is True
    assert result.geofence is not None and result.geofence.ok is True
    mission = result.mission
    assert mission is not None
    takeoff = mission.waypoints[0]
    assert takeoff.vehicle_action is VehicleAction.TAKEOFF
    assert takeoff.fly_through is False
    assert takeoff.lat == pytest.approx(spec.home.lat)
    assert takeoff.lon == pytest.approx(spec.home.lon)
    assert takeoff.relative_altitude_m == spec.altitude_m
    assert takeoff.speed_m_s == spec.speed_m_s
    for waypoint in mission.waypoints[1:]:
        assert waypoint.vehicle_action is VehicleAction.NONE
        assert waypoint.fly_through is True
    assert len(mission.waypoints) == len(mission.survey_points) + 1
    assert len(mission.survey_points) == 8
    assert mission.distance_m == pytest.approx(path_length_m(mission.waypoints))
    assert mission.distance_m > 0


def test_home_outside_the_fence_is_not_uploadable() -> None:
    spec = square_spec(home=xy_to_latlon(-50, 50, ORIGIN))
    result = plan_survey(spec)
    assert result.ok is False
    assert result.mission is not None
    assert "outside" in result.reason


def test_wide_spacing_produces_no_mission() -> None:
    result = plan_survey(square_spec(spacing_m=500))
    assert result.ok is False
    assert result.mission is None
    assert "no transect" in result.reason


def test_sample_field_contains_the_px4_home() -> None:
    home, polygon = px4_sample_field()
    assert point_inside(home, polygon)
    result = plan_survey(
        square_spec(
            polygon=polygon,
            home=home,
            spacing_m=20,
            angle_deg=90,
        )
    )
    assert result.ok is True
    assert result.mission is not None
    assert len(result.mission.waypoints) >= 3
