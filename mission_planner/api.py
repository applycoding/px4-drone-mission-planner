"""FastAPI surface for the map.

The process default is the fake vehicle, so the page can plan and "launch"
with no radio and no simulator. ``python -m mission_planner.sitl`` is the
process that binds a real MAVSDK system.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mission_planner.controller import LaunchResult, MissionController
from mission_planner.energy import PLACEHOLDER_NOTE, EnergyDecision, EnergyModel
from mission_planner.fake_system import FakeSystem
from mission_planner.fields import SAMPLE_FIELD_NOTE, px4_sample_field
from mission_planner.geofence import GeofenceReport
from mission_planner.geometry import LatLon
from mission_planner.mission import (
    PlanResult,
    SurveySpec,
    Waypoint,
    energy_for_mission,
    plan_survey,
)
from mission_planner.wire import PassthroughWire, WireFormat


class LatLonIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class SurveyIn(BaseModel):
    polygon: list[LatLonIn] = Field(min_length=3, max_length=200)
    home: LatLonIn
    spacing_m: float = Field(default=20, gt=0, le=500)
    angle_deg: float = Field(default=90, ge=0, le=360)
    altitude_m: float = Field(default=25, gt=0, le=120)
    speed_m_s: float = Field(default=5, gt=0, le=30)
    margin_m: float = Field(default=0, ge=0, le=100)
    battery_percent: float = Field(default=80, ge=0, le=100)
    acceptance_radius_m: float = Field(default=3, gt=0, le=50)


class RthIn(BaseModel):
    battery_percent: float | None = Field(default=None, ge=0, le=100)


def _web_dir() -> Path:
    path = Path(__file__).resolve().parents[1] / "web"
    if not path.is_dir():
        raise FileNotFoundError(f"web assets not found at {path}")
    return path


def _spec(body: SurveyIn) -> SurveySpec:
    return SurveySpec(
        polygon=tuple(LatLon(point.lat, point.lon) for point in body.polygon),
        home=LatLon(body.home.lat, body.home.lon),
        spacing_m=body.spacing_m,
        angle_deg=body.angle_deg,
        altitude_m=body.altitude_m,
        speed_m_s=body.speed_m_s,
        margin_m=body.margin_m,
        acceptance_radius_m=body.acceptance_radius_m,
    )


def _waypoint_json(waypoint: Waypoint) -> dict[str, object]:
    return {
        "lat": waypoint.lat,
        "lon": waypoint.lon,
        "relative_altitude_m": waypoint.relative_altitude_m,
        "speed_m_s": waypoint.speed_m_s,
        "fly_through": waypoint.fly_through,
        "vehicle_action": waypoint.vehicle_action.value,
        "acceptance_radius_m": waypoint.acceptance_radius_m,
    }


def _energy_json(decision: EnergyDecision | None) -> dict[str, object] | None:
    if decision is None:
        return None
    return asdict(decision)


def _geofence_json(report: GeofenceReport | None) -> dict[str, object] | None:
    if report is None:
        return None
    return {
        "ok": report.ok,
        "reason": report.reason,
        "violations": [asdict(item) for item in report.violations],
    }


def _preview_json(planned: PlanResult, battery_percent: float, model: EnergyModel) -> dict[str, object]:
    mission = planned.mission
    energy = None if mission is None else energy_for_mission(mission, battery_percent, model)
    if not planned.ok:
        reason = planned.reason
    elif energy is not None:
        reason = energy.reason
    else:
        reason = planned.reason
    distance = 0.0 if mission is None else mission.distance_m
    speed = 0.0 if mission is None else mission.speed_m_s
    return {
        "launchable": bool(planned.ok and energy is not None and energy.allowed),
        "reason": reason,
        "distance_m": distance,
        "time_at_set_speed_s": (distance / speed) if speed else None,
        "waypoint_count": 0 if mission is None else len(mission.waypoints),
        "waypoints": [] if mission is None else [_waypoint_json(item) for item in mission.waypoints],
        "home": None if mission is None else {"lat": mission.home.lat, "lon": mission.home.lon},
        "geofence": _geofence_json(planned.geofence),
        "energy": _energy_json(energy),
    }


def _launch_json(result: LaunchResult, vehicle: str) -> dict[str, object]:
    mission = result.mission
    return {
        "started": result.started,
        "stage": result.stage,
        "reason": result.reason,
        "remaining_percent": result.remaining_percent,
        "vehicle": vehicle,
        "distance_m": None if mission is None else mission.distance_m,
        "waypoint_count": 0 if mission is None else len(mission.waypoints),
        "waypoints": [] if mission is None else [_waypoint_json(item) for item in mission.waypoints],
        "home": None if mission is None else {"lat": mission.home.lat, "lon": mission.home.lon},
        "energy": _energy_json(result.energy),
    }


def _model_json(model: EnergyModel) -> dict[str, object]:
    return {
        "placeholder": model.placeholder,
        "capacity_wh": model.capacity_wh,
        "wh_per_km": model.wh_per_km,
        "min_start_percent": model.min_start_percent,
        "landing_reserve_percent": model.landing_reserve_percent,
        "rth_safety_factor": model.rth_safety_factor,
        "note": PLACEHOLDER_NOTE,
    }


def create_app(
    system: object | None = None,
    wire: WireFormat | None = None,
    address: str = "udpin://0.0.0.0:14540",
    vehicle_kind: str = "fake",
    energy_model: EnergyModel | None = None,
) -> FastAPI:
    vehicle = system if system is not None else FakeSystem()
    encoder = wire if wire is not None else PassthroughWire()
    model = energy_model or EnergyModel()
    controller = MissionController(vehicle, wire=encoder, address=address)
    app = FastAPI(
        title="PX4 survey mission planner",
        version="0.1.0",
        description="Lawnmower survey planner with geofence and return-to-home checks.",
    )
    app.state.system = vehicle
    app.state.controller = controller
    app.state.energy_model = model
    app.state.vehicle_kind = vehicle_kind
    app.state.address = address
    web = _web_dir()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(web / "index.html")

    @app.get("/api/status")
    def status() -> dict[str, object]:
        home, polygon = px4_sample_field()
        return {
            "vehicle": vehicle_kind,
            "address": address,
            "energy_model": _model_json(model),
            "sample_field": {
                "home": {"lat": home.lat, "lon": home.lon},
                "polygon": [{"lat": point.lat, "lon": point.lon} for point in polygon],
                "note": SAMPLE_FIELD_NOTE,
            },
        }

    @app.post("/api/preview")
    def preview(body: SurveyIn) -> dict[str, object]:
        return _preview_json(plan_survey(_spec(body)), body.battery_percent, model)

    @app.post("/api/launch")
    async def launch(body: SurveyIn) -> dict[str, object]:
        # The fake vehicle has no battery sensor. The form value is stored on
        # it so Launch and Preview agree. A MAVSDK vehicle keeps its own
        # telemetry and ignores this override.
        if vehicle_kind == "fake":
            vehicle.set_battery_fraction(body.battery_percent / 100.0)
            vehicle.set_home(body.home.lat, body.home.lon)
        result = await controller.launch(_spec(body), model)
        return _launch_json(result, vehicle_kind)

    @app.post("/api/rth-check")
    async def rth_check(body: RthIn) -> dict[str, object]:
        if vehicle_kind == "fake" and body.battery_percent is not None:
            vehicle.set_battery_fraction(body.battery_percent / 100.0)
        action = await controller.enforce_rth_reserve(model)
        return {
            "action": action.action,
            "remaining_percent": action.remaining_percent,
            "reason": action.reason,
            "vehicle": vehicle_kind,
        }

    app.mount("/static", StaticFiles(directory=web), name="static")
    return app


app = create_app()


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8091"))
    uvicorn.run(app, host=host, port=port)
