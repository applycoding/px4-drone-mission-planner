"""The sample field drawn around the PX4 simulator's usual start point.

The coordinate is the historical PX4 Gazebo iris home at Zurich Irchel
(about 47.397742, 8.545594). A world file can override it. The sample is an
80 m square, so a tenth of a metre of drift in that default still sits
inside the fence.
"""

from __future__ import annotations

from mission_planner.geometry import LatLon, xy_to_latlon

# Historical PX4 Gazebo iris / Zurich Irchel start. Not a survey measurement.
PX4_GAZEBO_IRIS_HOME = LatLon(47.397742, 8.545594)

SAMPLE_FIELD_NOTE = (
    "80 m square centered on the historical PX4 Gazebo iris home "
    "(Zurich Irchel). A world file can move the simulator; the vehicle home "
    "still has to fall inside the polygon before launch."
)


def px4_sample_field(half_size_m: float = 40.0) -> tuple[LatLon, tuple[LatLon, ...]]:
    if half_size_m <= 0:
        raise ValueError("half size must be positive")
    home = PX4_GAZEBO_IRIS_HOME
    corners = (
        (-half_size_m, -half_size_m),
        (half_size_m, -half_size_m),
        (half_size_m, half_size_m),
        (-half_size_m, half_size_m),
    )
    polygon = tuple(xy_to_latlon(east, north, home) for east, north in corners)
    return home, polygon
