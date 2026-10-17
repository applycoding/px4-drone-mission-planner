"""Run a survey on a vehicle that looks like a MAVSDK ``System``.

On a launch that is allowed to fly the controller does this, in order:

1. ``connect``
2. wait until ``core.connection_state`` reports connected
3. wait for an armable ``telemetry.health`` sample
4. read ``telemetry.home`` and plan from that home
5. read ``telemetry.battery`` (a fraction from 0 to 1, as MAVSDK reports it)
6. stop if the geofence or the energy rule says no
7. ``mission.set_return_to_launch_after_mission(True)``
8. ``geofence.upload_geofence``
9. ``mission.upload_mission``
10. ``action.arm``
11. ``mission.start_mission``

Steps 7–11 are skipped when the plan is refused, so the vehicle is not armed.
``enforce_rth_reserve`` is the in-flight half of the same battery rule: one
battery sample, and ``action.return_to_launch`` when it is at or below the
landing reserve.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, replace

from mission_planner.energy import EnergyDecision, EnergyModel, evaluate_path
from mission_planner.geometry import LatLon
from mission_planner.mission import SurveyMission, SurveySpec, plan_survey
from mission_planner.wire import PassthroughWire, WireFormat


def mavsdk_battery_percent(remaining_percent: float) -> float:
    """Convert MAVSDK's 0..1 battery fraction to a percentage.

    MAVSDK's telemetry battery ``remaining_percent`` is a fraction, despite
    the name. Values outside that range are refused rather than scaled.
    """
    if not math.isfinite(remaining_percent) or not 0.0 <= remaining_percent <= 1.0:
        raise ValueError("MAVSDK remaining_percent must be a fraction in [0, 1]")
    return remaining_percent * 100.0


@dataclass(frozen=True)
class LaunchResult:
    started: bool
    stage: str
    reason: str
    remaining_percent: float | None = None
    energy: EnergyDecision | None = None
    mission: SurveyMission | None = None


@dataclass(frozen=True)
class RthAction:
    action: str
    remaining_percent: float
    reason: str


class MissionController:
    def __init__(
        self,
        system: object,
        *,
        wire: WireFormat | None = None,
        address: str = "udpin://0.0.0.0:14540",
        timeout_s: float = 15.0,
    ) -> None:
        self._system = system
        self._wire = wire if wire is not None else PassthroughWire()
        self._address = address
        self._timeout_s = timeout_s

    async def launch(self, spec: SurveySpec, model: EnergyModel | None = None) -> LaunchResult:
        model = model or EnergyModel()
        try:
            await self._system.connect(system_address=self._address)
            await self._wait_connected()
            await self._wait_healthy()
            vehicle_home = await self._read_home()
            remaining = mavsdk_battery_percent((await self._read_battery()).remaining_percent)
        except (RuntimeError, ValueError, TimeoutError) as exc:
            return LaunchResult(started=False, stage="rejected", reason=str(exc))

        planned = plan_survey(replace(spec, home=vehicle_home))
        mission = planned.mission
        if not planned.ok or mission is None:
            return LaunchResult(
                started=False,
                stage="rejected",
                reason=planned.reason,
                remaining_percent=remaining,
                mission=mission,
            )

        decision = evaluate_path(list(mission.waypoints), mission.home, remaining, model)
        if not decision.allowed:
            return LaunchResult(
                started=False,
                stage="rejected",
                reason=decision.reason,
                remaining_percent=remaining,
                energy=decision,
                mission=mission,
            )

        try:
            await self._system.mission.set_return_to_launch_after_mission(True)
            await self._system.geofence.upload_geofence(self._wire.geofence_data(mission.fence))
            await self._system.mission.upload_mission(self._wire.mission_plan(mission))
        except Exception as exc:
            return LaunchResult(
                started=False,
                stage="rejected",
                reason=f"upload failed: {exc}",
                remaining_percent=remaining,
                energy=decision,
                mission=mission,
            )

        try:
            await self._system.action.arm()
        except Exception as exc:
            return LaunchResult(
                started=False,
                stage="uploaded",
                reason=f"arm failed: {exc}",
                remaining_percent=remaining,
                energy=decision,
                mission=mission,
            )

        try:
            await self._system.mission.start_mission()
        except Exception as exc:
            return LaunchResult(
                started=False,
                stage="armed",
                reason=f"start failed: {exc}",
                remaining_percent=remaining,
                energy=decision,
                mission=mission,
            )

        return LaunchResult(
            started=True,
            stage="started",
            reason="mission started and will return to launch when it finishes",
            remaining_percent=remaining,
            energy=decision,
            mission=mission,
        )

    async def enforce_rth_reserve(self, model: EnergyModel | None = None) -> RthAction:
        """Apply the in-flight reserve to a single battery sample."""
        model = model or EnergyModel()
        remaining = mavsdk_battery_percent((await self._read_battery()).remaining_percent)
        if remaining <= model.landing_reserve_percent:
            await self._system.action.return_to_launch()
            return RthAction(
                action="rtl",
                remaining_percent=remaining,
                reason="battery is at or below the landing reserve, returning to launch",
            )
        return RthAction(
            action="continue",
            remaining_percent=remaining,
            reason="battery is above the landing reserve",
        )

    async def _wait_connected(self) -> object:
        async def find() -> object:
            async for state in self._system.core.connection_state():
                if state.is_connected:
                    return state
            raise RuntimeError("vehicle did not connect")

        return await self._wait(find(), "timed out waiting for the vehicle to connect")

    async def _wait_healthy(self) -> object:
        async def find() -> object:
            async for health in self._system.telemetry.health():
                armable = getattr(health, "is_armable", True)
                if health.is_global_position_ok and health.is_home_position_ok and armable:
                    return health
            raise RuntimeError("health stream ended before the vehicle was armable")

        return await self._wait(find(), "timed out waiting for a global and home position")

    async def _wait(self, awaitable: object, timeout_reason: str) -> object:
        try:
            return await asyncio.wait_for(awaitable, self._timeout_s)
        except TimeoutError as exc:
            raise RuntimeError(timeout_reason) from exc

    async def _read_home(self) -> LatLon:
        sample = await self._first(self._system.telemetry.home(), "home")
        return LatLon(sample.latitude_deg, sample.longitude_deg)

    async def _read_battery(self) -> object:
        return await self._first(self._system.telemetry.battery(), "battery")

    async def _first(self, stream: object, label: str) -> object:
        async for item in stream:
            return item
        raise RuntimeError(f"{label} stream ended without a sample")
