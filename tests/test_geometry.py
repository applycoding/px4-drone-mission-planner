import pytest

from mission_planner.fields import px4_sample_field
from mission_planner.geofence import point_inside
from mission_planner.geometry import (
    LatLon,
    generate_lawnmower,
    latlon_to_xy,
    xy_to_latlon,
)

from tests.support import ORIGIN, square_polygon


def _xy(point: LatLon) -> tuple[float, float]:
    return latlon_to_xy(point, ORIGIN)


def test_east_west_lawnmower_on_a_square() -> None:
    path = generate_lawnmower(square_polygon(), spacing_m=25, angle_deg=90)
    assert len(path) == 8
    expected = [
        (0, 12.5),
        (100, 12.5),
        (100, 37.5),
        (0, 37.5),
        (0, 62.5),
        (100, 62.5),
        (100, 87.5),
        (0, 87.5),
    ]
    for point, (east, north) in zip(path, expected, strict=True):
        got_east, got_north = _xy(point)
        assert got_east == pytest.approx(east, abs=0.05)
        assert got_north == pytest.approx(north, abs=0.05)
    # Adjacent legs travel in opposite directions.
    assert _xy(path[1])[0] > _xy(path[0])[0]
    assert _xy(path[3])[0] < _xy(path[2])[0]


def test_north_south_heading_runs_along_y() -> None:
    path = generate_lawnmower(square_polygon(), spacing_m=25, angle_deg=0)
    first_east, first_north = _xy(path[0])
    second_east, second_north = _xy(path[1])
    assert first_east == pytest.approx(87.5, abs=0.05)
    assert second_east == pytest.approx(87.5, abs=0.05)
    assert first_north == pytest.approx(0, abs=0.05)
    assert second_north == pytest.approx(100, abs=0.05)
    third_east, third_north = _xy(path[2])
    fourth_north = _xy(path[3])[1]
    assert third_east == pytest.approx(62.5, abs=0.05)
    assert third_north == pytest.approx(100, abs=0.05)
    assert fourth_north == pytest.approx(0, abs=0.05)


def test_winding_does_not_change_the_path() -> None:
    polygon = list(square_polygon())
    forward = generate_lawnmower(polygon, spacing_m=25, angle_deg=90)
    backward = generate_lawnmower(list(reversed(polygon)), spacing_m=25, angle_deg=90)
    assert len(forward) == len(backward)
    for left, right in zip(forward, backward, strict=True):
        assert left.lat == pytest.approx(right.lat, abs=1e-9)
        assert left.lon == pytest.approx(right.lon, abs=1e-9)


def test_concave_l_uses_the_local_width() -> None:
    corners = (
        (0, 0),
        (100, 0),
        (100, 40),
        (40, 40),
        (40, 100),
        (0, 100),
    )
    polygon = [xy_to_latlon(east, north, ORIGIN) for east, north in corners]
    path = generate_lawnmower(polygon, spacing_m=20, angle_deg=90)
    expected = [
        (0, 10),
        (100, 10),
        (100, 30),
        (0, 30),
        (0, 50),
        (40, 50),
        (40, 70),
        (0, 70),
        (0, 90),
        (40, 90),
    ]
    assert len(path) == len(expected)
    for point, (east, north) in zip(path, expected, strict=True):
        got_east, got_north = _xy(point)
        assert got_east == pytest.approx(east, abs=0.05)
        assert got_north == pytest.approx(north, abs=0.05)


def test_margin_insets_the_square() -> None:
    path = generate_lawnmower(square_polygon(), spacing_m=25, angle_deg=90, margin_m=10)
    assert len(path) == 6
    expected = [
        (10, 22.5),
        (90, 22.5),
        (90, 47.5),
        (10, 47.5),
        (10, 72.5),
        (90, 72.5),
    ]
    for point, (east, north) in zip(path, expected, strict=True):
        got_east, got_north = _xy(point)
        assert got_east == pytest.approx(east, abs=0.05)
        assert got_north == pytest.approx(north, abs=0.05)


def test_spacing_wider_than_the_field_is_empty() -> None:
    assert generate_lawnmower(square_polygon(), spacing_m=250, angle_deg=90) == []


def test_generated_points_stay_inside() -> None:
    polygon = square_polygon()
    path = generate_lawnmower(polygon, spacing_m=25, angle_deg=90)
    assert path
    assert all(point_inside(point, polygon) for point in path)


def test_sample_field_path_stays_inside_the_ring() -> None:
    _home, polygon = px4_sample_field()
    path = generate_lawnmower(polygon, spacing_m=20, angle_deg=90)
    assert len(path) >= 2
    assert all(point_inside(point, polygon) for point in path)


@pytest.mark.parametrize(
    ("polygon", "spacing", "margin", "message"),
    [
        (square_polygon()[:2], 25, 0, "at least 3"),
        (square_polygon(), 0, 0, "spacing"),
        (square_polygon(), -5, 0, "spacing"),
        (square_polygon(), 25, -1, "margin"),
        (
            [xy_to_latlon(east, north, ORIGIN) for east, north in ((0, 0), (10, 0), (20, 0))],
            5,
            0,
            "area",
        ),
    ],
)
def test_rejects_bad_input(polygon, spacing, margin, message) -> None:
    with pytest.raises(ValueError, match=message):
        generate_lawnmower(polygon, spacing_m=spacing, angle_deg=90, margin_m=margin)
