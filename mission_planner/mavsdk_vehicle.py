"""Encode a survey as MAVSDK mission and geofence objects.

Importing this module requires the optional ``sitl`` extra (``mavsdk``).
Unit tests do not import it; they talk to ``FakeSystem`` instead.
"""

from __future__ import annotations

from typing import Sequence, assert_never

from mavsdk.geofence import Circle, FenceType, GeofenceData, Point, Polygon
from mavsdk.mission import MissionItem, MissionPlan

from mission_planner.geometry import LatLon
from mission_planner.mission import SurveyMission, VehicleAction

_NAN = float("nan")


class MavsdkWire:
    """Wire format for a real ``mavsdk.System``."""

    def mission_plan(self, mission: SurveyMission) -> MissionPlan:
        items = [
            MissionItem(
                waypoint.lat,
                waypoint.lon,
                waypoint.relative_altitude_m,
                waypoint.speed_m_s,
                waypoint.fly_through,
                _NAN,
                _NAN,
                MissionItem.CameraAction.NONE,
                _NAN,
                _NAN,
                waypoint.acceptance_radius_m,
                _NAN,
                _NAN,
                _sdk_vehicle_action(waypoint.vehicle_action),
            )
            for waypoint in mission.waypoints
        ]
        return MissionPlan(items)

    def geofence_data(self, fence: Sequence[LatLon]) -> GeofenceData:
        polygon = Polygon(
            [Point(point.lat, point.lon) for point in fence],
            FenceType.INCLUSION,
        )
        # GeofenceData carries circles as well as polygons. The MAVSDK
        # geofence example sends a zero-radius circle when the fence is only
        # a polygon.
        empty_circle = Circle(Point(0.0, 0.0), 0.0, FenceType.INCLUSION)
        return GeofenceData([polygon], [empty_circle])


def _sdk_vehicle_action(action: VehicleAction) -> object:
    if action is VehicleAction.TAKEOFF:
        return MissionItem.VehicleAction.TAKEOFF
    if action is VehicleAction.NONE:
        return MissionItem.VehicleAction.NONE
    assert_never(action)
