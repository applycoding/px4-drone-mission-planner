"""A fake ``mavsdk.System``.

The run controller calls the same plugins MAVSDK-Python exposes: ``core``,
``telemetry``, ``mission``, ``action``, and ``geofence``. Battery
``remaining_percent`` is a fraction in ``[0, 1]``, matching MAVSDK's
telemetry battery message, not a 0–100 percentage.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class FakeConnectionState:
    is_connected: bool = True


@dataclass
class FakeHealth:
    is_global_position_ok: bool = True
    is_home_position_ok: bool = True
    is_armable: bool = True


@dataclass
class FakeBattery:
    remaining_percent: float = 0.8
    voltage_v: float = 16.0


@dataclass
class FakePosition:
    latitude_deg: float = 47.397742
    longitude_deg: float = 8.545594
    relative_altitude_m: float = 0.0


class _Stream:
    def __init__(
        self,
        items: list[object],
        events: list[str],
        name: str,
        delay_s: float = 0.0,
    ) -> None:
        self._items = items
        self._events = events
        self._name = name
        self._delay_s = delay_s

    def __aiter__(self) -> _Stream:
        self._events.append(self._name)
        self._index = 0
        self._paused = False
        return self

    async def __anext__(self) -> object:
        if self._paused and self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        self._paused = True
        return item


class FakeCore:
    def __init__(self, events: list[str], connected: bool) -> None:
        self._events = events
        self.connected = connected

    def connection_state(self) -> _Stream:
        return _Stream(
            [FakeConnectionState(self.connected)], self._events, "connection_state"
        )


class FakeMission:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.rtl_after_mission: bool | None = None
        self.uploaded: object | None = None
        self.started = False
        self.fail_upload = False

    async def set_return_to_launch_after_mission(self, enable: bool) -> None:
        self._events.append("set_return_to_launch_after_mission")
        self.rtl_after_mission = enable

    async def upload_mission(self, plan: object) -> None:
        self._events.append("upload_mission")
        if self.fail_upload:
            raise RuntimeError("upload failed")
        self.uploaded = plan

    async def start_mission(self) -> None:
        self._events.append("start_mission")
        self.started = True


class FakeAction:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.armed = False
        self.rtl_called = False
        self.fail_arm = False

    async def arm(self) -> None:
        self._events.append("arm")
        if self.fail_arm:
            raise RuntimeError("arm denied")
        self.armed = True

    async def return_to_launch(self) -> None:
        self._events.append("return_to_launch")
        self.rtl_called = True


class FakeTelemetry:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.health_reading = FakeHealth()
        self.battery_reading = FakeBattery()
        self.home_reading = FakePosition()
        self.health_delay_s = 0.0

    def health(self) -> _Stream:
        return _Stream(
            [self.health_reading],
            self._events,
            "health",
            delay_s=self.health_delay_s,
        )

    def battery(self) -> _Stream:
        return _Stream([self.battery_reading], self._events, "battery")

    def home(self) -> _Stream:
        return _Stream([self.home_reading], self._events, "home")


class FakeGeofence:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.uploaded: object | None = None
        self.fail = False

    async def upload_geofence(self, data: object) -> None:
        self._events.append("upload_geofence")
        if self.fail:
            raise RuntimeError("geofence rejected")
        self.uploaded = data


class FakeSystem:
    """In-process stand-in for ``mavsdk.System``."""

    kind = "fake"

    def __init__(
        self,
        *,
        connected: bool = True,
        battery_fraction: float = 0.8,
        home_lat: float = 47.397742,
        home_lon: float = 8.545594,
    ) -> None:
        self.events: list[str] = []
        self.core = FakeCore(self.events, connected)
        self.mission = FakeMission(self.events)
        self.action = FakeAction(self.events)
        self.telemetry = FakeTelemetry(self.events)
        self.geofence = FakeGeofence(self.events)
        self.connected_address: str | None = None
        self.set_battery_fraction(battery_fraction)
        self.set_home(home_lat, home_lon)

    async def connect(self, system_address: str) -> None:
        self.events.append("connect")
        self.connected_address = system_address

    def set_battery_fraction(self, fraction: float) -> None:
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("battery fraction must be between 0 and 1")
        self.telemetry.battery_reading.remaining_percent = fraction

    def set_home(self, lat: float, lon: float) -> None:
        self.telemetry.home_reading.latitude_deg = lat
        self.telemetry.home_reading.longitude_deg = lon
