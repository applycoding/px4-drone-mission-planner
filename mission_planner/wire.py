"""Encodes a survey into whatever object ``upload_mission`` expects.

The controller stays free of the MAVSDK import. Tests pass
``PassthroughWire``, which stores the planner's own mission object. The
SITL entry point passes ``MavsdkWire``.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from mission_planner.geometry import LatLon
from mission_planner.mission import SurveyMission


class WireFormat(Protocol):
    def mission_plan(self, mission: SurveyMission) -> object: ...

    def geofence_data(self, fence: Sequence[LatLon]) -> object: ...


class PassthroughWire:
    """Encoder for the fake MAVSDK system. Stores planner objects as-is."""

    def mission_plan(self, mission: SurveyMission) -> SurveyMission:
        return mission

    def geofence_data(self, fence: Sequence[LatLon]) -> list[LatLon]:
        return list(fence)
