"""Local-tangent survey geometry.

Lat/lon is projected to a flat east/north frame in meters around one origin.
That is accurate enough for a field a few kilometres across, which is the
scale this planner is for. It is not a geodesy library.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, Sequence

METERS_PER_DEG_LAT = 111_320.0
MIN_POLYGON_AREA_M2 = 1.0
MIN_LEG_M = 1.0


class GeoPoint(Protocol):
    lat: float
    lon: float


@dataclass(frozen=True)
class LatLon:
    lat: float
    lon: float


def meters_per_deg_lon(lat_deg: float) -> float:
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat_deg))


def latlon_to_xy(point: GeoPoint, origin: GeoPoint) -> tuple[float, float]:
    east = (point.lon - origin.lon) * meters_per_deg_lon(origin.lat)
    north = (point.lat - origin.lat) * METERS_PER_DEG_LAT
    return east, north


def xy_to_latlon(east_m: float, north_m: float, origin: GeoPoint) -> LatLon:
    lat = origin.lat + north_m / METERS_PER_DEG_LAT
    lon_scale = meters_per_deg_lon(origin.lat)
    if abs(lon_scale) < 1e-9:
        raise ValueError("longitude is undefined this close to a pole")
    lon = origin.lon + east_m / lon_scale
    return LatLon(lat, lon)


def distance_m(a: GeoPoint, b: GeoPoint) -> float:
    east, north = latlon_to_xy(b, a)
    return math.hypot(east, north)


def path_length_m(points: Sequence[GeoPoint]) -> float:
    total = 0.0
    for start, end in zip(points, points[1:]):
        total += distance_m(start, end)
    return total


def farthest_from_m(origin: GeoPoint, points: Sequence[GeoPoint]) -> float:
    if not points:
        return 0.0
    return max(distance_m(origin, point) for point in points)


def centroid(points: Sequence[LatLon]) -> LatLon:
    if not points:
        raise ValueError("centroid of an empty ring is undefined")
    return LatLon(
        sum(point.lat for point in points) / len(points),
        sum(point.lon for point in points) / len(points),
    )


def _require_finite(points: Sequence[LatLon]) -> None:
    for index, point in enumerate(points):
        if not math.isfinite(point.lat) or not math.isfinite(point.lon):
            raise ValueError(f"point {index} has a non-finite coordinate")
        if not -90.0 <= point.lat <= 90.0:
            raise ValueError(f"point {index} latitude is outside -90..90")
        if not -180.0 <= point.lon <= 180.0:
            raise ValueError(f"point {index} longitude is outside -180..180")


def clean_ring(points: Sequence[LatLon]) -> list[LatLon]:
    """Drop a repeated closing vertex and consecutive duplicates."""
    _require_finite(points)
    cleaned: list[LatLon] = []
    for point in points:
        if cleaned and point == cleaned[-1]:
            continue
        cleaned.append(point)
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1]:
        cleaned.pop()
    return cleaned


def _signed_area_m2(xy: Sequence[tuple[float, float]]) -> float:
    area = 0.0
    count = len(xy)
    for index in range(count):
        x1, y1 = xy[index]
        x2, y2 = xy[(index + 1) % count]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _project_ring(
    points: Sequence[LatLon], origin: LatLon
) -> list[tuple[float, float]]:
    return [latlon_to_xy(point, origin) for point in points]


def _along_across(
    east: float, north: float, angle_deg: float
) -> tuple[float, float]:
    """Express a point along the transect heading and across it.

    ``angle_deg`` is the transect heading, degrees clockwise from north.
    ``along`` increases in the direction of travel. ``across`` increases to
    the left of travel.
    """
    theta = math.radians(angle_deg)
    east_hat = math.sin(theta)
    north_hat = math.cos(theta)
    along = east * east_hat + north * north_hat
    across = east * (-north_hat) + north * east_hat
    return along, across


def _east_north(
    along: float, across: float, angle_deg: float
) -> tuple[float, float]:
    theta = math.radians(angle_deg)
    east_hat = math.sin(theta)
    north_hat = math.cos(theta)
    east = along * east_hat + across * (-north_hat)
    north = along * north_hat + across * east_hat
    return east, north


def _horizontal_intersections(
    ring: Sequence[tuple[float, float]], across: float
) -> list[float]:
    """Along-coordinates where a constant-across line meets the ring."""
    hits: list[float] = []
    count = len(ring)
    for index in range(count):
        along_a, across_a = ring[index]
        along_b, across_b = ring[(index + 1) % count]
        # Half-open so a vertex is owned by one edge. Horizontal edges contribute
        # no extra hit; their neighbours already end on the line.
        crosses = (across_a <= across < across_b) or (across_b <= across < across_a)
        if not crosses:
            continue
        span = across_b - across_a
        t = (across - across_a) / span
        hits.append(along_a + t * (along_b - along_a))
    hits.sort()
    return hits


def _inset_leg(
    start_along: float, end_along: float, margin_m: float
) -> tuple[float, float] | None:
    if start_along <= end_along:
        start = start_along + margin_m
        end = end_along - margin_m
    else:
        start = start_along - margin_m
        end = end_along + margin_m
    if abs(end - start) < MIN_LEG_M:
        return None
    return start, end


def generate_lawnmower(
    polygon: Sequence[LatLon],
    spacing_m: float,
    angle_deg: float = 90.0,
    margin_m: float = 0.0,
) -> list[LatLon]:
    """Build a lawnmower survey inside ``polygon``.

    Transects run on ``angle_deg`` (clockwise from north) and step by
    ``spacing_m``. ``margin_m`` insets the swept band and shortens each leg.
    The polygon must be a simple ring. Self-intersections are not supported.
    An empty list means the spacing and margin leave nothing to fly.
    """
    if spacing_m <= 0:
        raise ValueError("spacing must be positive")
    if margin_m < 0:
        raise ValueError("margin must be zero or positive")
    if not math.isfinite(angle_deg):
        raise ValueError("angle must be finite")

    ring = clean_ring(polygon)
    if len(ring) < 3:
        raise ValueError("polygon needs at least 3 points")

    origin = centroid(ring)
    east_north = _project_ring(ring, origin)
    if abs(_signed_area_m2(east_north)) < MIN_POLYGON_AREA_M2:
        raise ValueError("polygon area is below 1 m²")

    heading = angle_deg % 360.0
    frame = [_along_across(east, north, heading) for east, north in east_north]
    across_values = [across for _, across in frame]
    inner_min = min(across_values) + margin_m
    inner_max = max(across_values) - margin_m
    if inner_max - inner_min <= 0:
        return []

    cursor = inner_min + spacing_m / 2.0
    transects: list[float] = []
    while cursor < inner_max - 1e-6:
        transects.append(cursor)
        cursor += spacing_m

    path_frame: list[tuple[float, float]] = []
    travel_positive = True
    for across in transects:
        hits = _horizontal_intersections(frame, across)
        if len(hits) < 2 or len(hits) % 2 != 0:
            continue
        pairs = list(zip(hits[0::2], hits[1::2]))
        if not travel_positive:
            pairs = [(end, start) for start, end in reversed(pairs)]
        emitted = False
        for start_along, end_along in pairs:
            leg = _inset_leg(start_along, end_along, margin_m)
            if leg is None:
                continue
            start, end = leg
            path_frame.append((start, across))
            path_frame.append((end, across))
            emitted = True
        if emitted:
            travel_positive = not travel_positive

    path: list[LatLon] = []
    for along, across in path_frame:
        east, north = _east_north(along, across, heading)
        path.append(xy_to_latlon(east, north, origin))
    return path
