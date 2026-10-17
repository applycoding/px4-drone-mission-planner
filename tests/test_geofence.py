import pytest

from mission_planner.geofence import (
    boundary_distance_m,
    point_inside,
    validate_geofence,
)
from mission_planner.geometry import LatLon, generate_lawnmower, xy_to_latlon

from tests.support import ORIGIN, square_polygon


def _at(east: float, north: float) -> LatLon:
    return xy_to_latlon(east, north, ORIGIN)


def test_inside_outside_and_boundary() -> None:
    fence = square_polygon()
    assert point_inside(_at(50, 50), fence)
    assert not point_inside(_at(50, -10), fence)
    assert point_inside(_at(50, 0), fence)
    assert point_inside(_at(0, 0), fence)
    assert boundary_distance_m(_at(50, 5), fence) == pytest.approx(5, abs=0.05)
    assert boundary_distance_m(_at(50, -5), fence) == pytest.approx(-5, abs=0.05)


def test_margin_rejects_points_close_to_the_edge() -> None:
    fence = square_polygon()
    home = _at(50, 50)
    close = validate_geofence([_at(50, 5)], fence, home, margin_m=10)
    assert close.ok is False
    assert "margin" in close.reason

    clear = validate_geofence([_at(50, 50)], fence, home, margin_m=10)
    assert clear.ok is True

    on_the_margin = validate_geofence([_at(50, 10)], fence, home, margin_m=10)
    assert on_the_margin.ok is True


def test_generated_survey_passes() -> None:
    fence = square_polygon()
    home = _at(50, 50)
    survey = generate_lawnmower(fence, spacing_m=25, angle_deg=90)
    report = validate_geofence(survey, fence, home, margin_m=0)
    assert report.ok is True
    assert report.violations == ()


def test_outside_waypoint_is_named() -> None:
    fence = square_polygon()
    report = validate_geofence([_at(50, 50), _at(150, 50)], fence, _at(50, 50))
    assert report.ok is False
    assert any("waypoint 1" in item.detail and "outside" in item.detail for item in report.violations)


def test_home_outside_is_its_own_violation() -> None:
    fence = square_polygon()
    report = validate_geofence([_at(50, 50)], fence, _at(-20, 50))
    assert report.ok is False
    assert report.violations[0].index == -1
    assert "home" in report.reason


def test_chord_across_a_notch_is_rejected() -> None:
    corners = ((0, 0), (5, 0), (5, 2), (2, 2), (2, 5), (0, 5))
    fence = [_at(east, north) for east, north in corners]
    home = _at(1, 1)
    foot = _at(4, 1)
    stem = _at(1, 4)
    assert point_inside(home, fence)
    assert point_inside(foot, fence)
    assert point_inside(stem, fence)
    assert not point_inside(_at(3, 3), fence)

    report = validate_geofence([foot, stem], fence, home)
    assert report.ok is False
    assert any("leaves the geofence" in item.detail for item in report.violations)

    staying = validate_geofence([_at(4, 1)], fence, home)
    assert staying.ok is True
