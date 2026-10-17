"""Turn a polygon into a survey mission.

The first uploaded item is a takeoff at home. The rest are fly-through
lawnmower vertices. Return-to-launch is not a mission item; the run
controller sets that flag on the vehicle before upload, which is how
MAVSDK applies it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from mission_planner.energy import EnergyDecision, EnergyModel, evaluate_path
from mission_planner.geofence import GeofenceReport, validate_geofence
from mission_planner.geometry import LatLon, clean_ring, generate_lawnmower, path_length_m


class VehicleAction(Enum):
    TAKEOFF = "takeoff"
    NONE = "none"


@dataclass(frozen=True)
class Waypoint:
    lat: float
    lon: float
    relative_altitude_m: float
    speed_m_s: float
    fly_through: bool
    vehicle_action: VehicleAction
    acceptance_radius_m: float


@dataclass(frozen=True)
class SurveySpec:
    polygon: tuple[LatLon, ...]
    home: LatLon
    spacing_m: float
    angle_deg: float
    altitude_m: float
    speed_m_s: float
    margin_m: float = 0.0
    acceptance_radius_m: float = 3.0


@dataclass(frozen=True)
class SurveyMission:
    home: LatLon
    fence: tuple[LatLon, ...]
    waypoints: tuple[Waypoint, ...]
    distance_m: float
    spacing_m: float
    angle_deg: float
    altitude_m: float
    speed_m_s: float

    @property
    def survey_points(self) -> tuple[LatLon, ...]:
        """Lawnmower vertices, without the takeoff item at home."""
        return tuple(LatLon(item.lat, item.lon) for item in self.waypoints[1:])


@dataclass(frozen=True)
class PlanResult:
    ok: bool
    reason: str
    mission: SurveyMission | None
    geofence: GeofenceReport | None


def plan_survey(spec: SurveySpec) -> PlanResult:
    """Plan a survey. ``ok`` is false when the path must not be uploaded."""
    if spec.altitude_m <= 0:
        return PlanResult(False, "altitude must be positive", None, None)
    if spec.speed_m_s <= 0:
        return PlanResult(False, "speed must be positive", None, None)
    if spec.acceptance_radius_m <= 0:
        return PlanResult(False, "acceptance radius must be positive", None, None)

    try:
        ring = tuple(clean_ring(spec.polygon))
        survey = generate_lawnmower(
            ring,
            spacing_m=spec.spacing_m,
            angle_deg=spec.angle_deg,
            margin_m=spec.margin_m,
        )
    except ValueError as exc:
        return PlanResult(ok=False, reason=str(exc), mission=None, geofence=None)

    if len(survey) < 2:
        return PlanResult(
            ok=False,
            reason="the spacing and margin leave no transect inside the polygon",
            mission=None,
            geofence=None,
        )

    try:
        fence_report = validate_geofence(
            survey, ring, spec.home, margin_m=spec.margin_m
        )
    except ValueError as exc:
        return PlanResult(ok=False, reason=str(exc), mission=None, geofence=None)

    takeoff = Waypoint(
        lat=spec.home.lat,
        lon=spec.home.lon,
        relative_altitude_m=spec.altitude_m,
        speed_m_s=spec.speed_m_s,
        fly_through=False,
        vehicle_action=VehicleAction.TAKEOFF,
        acceptance_radius_m=spec.acceptance_radius_m,
    )
    legs = tuple(
        Waypoint(
            lat=point.lat,
            lon=point.lon,
            relative_altitude_m=spec.altitude_m,
            speed_m_s=spec.speed_m_s,
            fly_through=True,
            vehicle_action=VehicleAction.NONE,
            acceptance_radius_m=spec.acceptance_radius_m,
        )
        for point in survey
    )
    waypoints = (takeoff, *legs)
    mission = SurveyMission(
        home=spec.home,
        fence=ring,
        waypoints=waypoints,
        distance_m=path_length_m(waypoints),
        spacing_m=spec.spacing_m,
        angle_deg=spec.angle_deg % 360.0,
        altitude_m=spec.altitude_m,
        speed_m_s=spec.speed_m_s,
    )
    if not fence_report.ok:
        return PlanResult(
            ok=False,
            reason=fence_report.reason,
            mission=mission,
            geofence=fence_report,
        )
    return PlanResult(
        ok=True,
        reason=fence_report.reason,
        mission=mission,
        geofence=fence_report,
    )


def energy_for_mission(
    mission: SurveyMission,
    remaining_percent: float,
    model: EnergyModel | None = None,
) -> EnergyDecision:
    return evaluate_path(
        list(mission.waypoints),
        mission.home,
        remaining_percent,
        model,
    )
