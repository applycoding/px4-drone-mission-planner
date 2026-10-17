"""Shared polygons for the unit tests. The square sits on the equator so metres map cleanly."""

from __future__ import annotations

from mission_planner.geometry import LatLon, xy_to_latlon
from mission_planner.mission import SurveySpec

ORIGIN = LatLon(0.0, 0.0)


def square_polygon(size_m: float = 100.0) -> tuple[LatLon, ...]:
    return tuple(
        xy_to_latlon(east, north, ORIGIN)
        for east, north in (
            (0.0, 0.0),
            (size_m, 0.0),
            (size_m, size_m),
            (0.0, size_m),
        )
    )


def square_spec(
    *,
    size_m: float = 100.0,
    spacing_m: float = 25.0,
    angle_deg: float = 90.0,
    altitude_m: float = 25.0,
    speed_m_s: float = 5.0,
    margin_m: float = 0.0,
    polygon: tuple[LatLon, ...] | None = None,
    home: LatLon | None = None,
) -> SurveySpec:
    ring = polygon if polygon is not None else square_polygon(size_m)
    origin_home = home if home is not None else xy_to_latlon(size_m / 2.0, size_m / 2.0, ORIGIN)
    return SurveySpec(
        polygon=ring,
        home=origin_home,
        spacing_m=spacing_m,
        angle_deg=angle_deg,
        altitude_m=altitude_m,
        speed_m_s=speed_m_s,
        margin_m=margin_m,
    )
