"""Inclusion-fence checks for a survey.

A point on the boundary counts as inside. ``margin_m`` is extra clearance
from the boundary for the survey legs, measured in the same local tangent
frame as the path generator. The home position only has to be inside the
ring: PX4 rejects an inclusion fence that leaves home outside, and the
margin is about the camera path rather than the launch point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from mission_planner.geometry import LatLon, centroid, clean_ring, latlon_to_xy

_BOUNDARY_EPS_M = 1e-4
_MARGIN_TOL_M = 1e-3
_CROSS_EPS_M2 = 1e-6


@dataclass(frozen=True)
class Violation:
    index: int
    lat: float
    lon: float
    detail: str


@dataclass(frozen=True)
class GeofenceReport:
    ok: bool
    violations: tuple[Violation, ...]

    @property
    def reason(self) -> str:
        if self.ok:
            return "home and the survey path are inside the geofence"
        return self.violations[0].detail


def _ring_xy(
    fence: Sequence[LatLon],
) -> tuple[LatLon, list[tuple[float, float]]]:
    ring = clean_ring(fence)
    if len(ring) < 3:
        raise ValueError("geofence needs at least 3 points")
    origin = centroid(ring)
    return origin, [latlon_to_xy(point, origin) for point in ring]


def _distance_to_segment(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    abx = bx - ax
    aby = by - ay
    length_sq = abx * abx + aby * aby
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / length_sq))
    return math.hypot(px - (ax + t * abx), py - (ay + t * aby))


def _on_boundary(x: float, y: float, ring: Sequence[tuple[float, float]]) -> bool:
    count = len(ring)
    for index in range(count):
        ax, ay = ring[index]
        bx, by = ring[(index + 1) % count]
        if _distance_to_segment(x, y, ax, ay, bx, by) <= _BOUNDARY_EPS_M:
            return True
    return False


def _distance_to_boundary(x: float, y: float, ring: Sequence[tuple[float, float]]) -> float:
    count = len(ring)
    best = math.inf
    for index in range(count):
        ax, ay = ring[index]
        bx, by = ring[(index + 1) % count]
        best = min(best, _distance_to_segment(x, y, ax, ay, bx, by))
    return best


def _contains_xy(x: float, y: float, ring: Sequence[tuple[float, float]]) -> bool:
    if _on_boundary(x, y, ring):
        return True
    inside = False
    count = len(ring)
    for index in range(count):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def _proper_crossing(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    """True when AB and CD cross in their interiors.

    Touching or running along an edge is boundary contact, which this fence
    allows. A transect that merely ends on the ring is not a violation.
    """

    def orient(
        p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]
    ) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    if (
        abs(o1) <= _CROSS_EPS_M2
        or abs(o2) <= _CROSS_EPS_M2
        or abs(o3) <= _CROSS_EPS_M2
        or abs(o4) <= _CROSS_EPS_M2
    ):
        return False
    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)


def _segment_inside(
    start: tuple[float, float],
    end: tuple[float, float],
    ring: Sequence[tuple[float, float]],
) -> bool:
    if not _contains_xy(start[0], start[1], ring) or not _contains_xy(end[0], end[1], ring):
        return False
    count = len(ring)
    for index in range(count):
        edge_start = ring[index]
        edge_end = ring[(index + 1) % count]
        if _proper_crossing(start, end, edge_start, edge_end):
            return False
    return True


def point_inside(point: LatLon, fence: Sequence[LatLon]) -> bool:
    origin, ring = _ring_xy(fence)
    east, north = latlon_to_xy(point, origin)
    return _contains_xy(east, north, ring)


def boundary_distance_m(point: LatLon, fence: Sequence[LatLon]) -> float:
    """Meters from ``point`` to the nearest edge. Negative when outside."""
    origin, ring = _ring_xy(fence)
    east, north = latlon_to_xy(point, origin)
    distance = _distance_to_boundary(east, north, ring)
    if _contains_xy(east, north, ring):
        return distance
    return -distance


def validate_geofence(
    survey: Sequence[LatLon],
    fence: Sequence[LatLon],
    home: LatLon,
    margin_m: float = 0.0,
) -> GeofenceReport:
    """Check home, survey vertices, and the straight legs between them.

    ``survey`` is the lawnmower only. The leg from home to the first survey
    point is checked too, because that is part of the uploaded mission.
    """
    if margin_m < 0:
        raise ValueError("margin must be zero or positive")
    origin, ring = _ring_xy(fence)
    violations: list[Violation] = []

    home_xy = latlon_to_xy(home, origin)
    if not _contains_xy(home_xy[0], home_xy[1], ring):
        violations.append(
            Violation(
                index=-1,
                lat=home.lat,
                lon=home.lon,
                detail="home is outside the geofence",
            )
        )

    survey_xy: list[tuple[float, float]] = []
    for index, point in enumerate(survey):
        xy = latlon_to_xy(point, origin)
        survey_xy.append(xy)
        if not _contains_xy(xy[0], xy[1], ring):
            violations.append(
                Violation(
                    index=index,
                    lat=point.lat,
                    lon=point.lon,
                    detail=f"waypoint {index} is outside the geofence",
                )
            )
            continue
        if margin_m > 0 and _distance_to_boundary(xy[0], xy[1], ring) + _MARGIN_TOL_M < margin_m:
            violations.append(
                Violation(
                    index=index,
                    lat=point.lat,
                    lon=point.lon,
                    detail=(
                        f"waypoint {index} is closer to the boundary than "
                        f"the {margin_m:.0f} m margin"
                    ),
                )
            )

    full_path = [home_xy, *survey_xy]
    for index in range(len(full_path) - 1):
        if not _segment_inside(full_path[index], full_path[index + 1], ring):
            violations.append(
                Violation(
                    index=index - 1,
                    lat=survey[index].lat if index < len(survey) else home.lat,
                    lon=survey[index].lon if index < len(survey) else home.lon,
                    detail=f"leg {index} leaves the geofence",
                )
            )

    return GeofenceReport(ok=not violations, violations=tuple(violations))
