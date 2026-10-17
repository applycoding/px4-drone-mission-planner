"""Serve the planner against a real MAVSDK ``System``.

Requires the optional dependency: ``pip install -e '.[sitl]'``.

The process listens for PX4 on ``PLANNER_SYSTEM_ADDRESS`` (default
``udpin://0.0.0.0:14540``) and serves the map on ``PORT`` (default 8091).
"""

from __future__ import annotations

import os

import uvicorn
from mavsdk import System

from mission_planner.api import create_app
from mission_planner.mavsdk_vehicle import MavsdkWire


def main() -> None:
    address = os.environ.get("PLANNER_SYSTEM_ADDRESS", "udpin://0.0.0.0:14540")
    port = int(os.environ.get("PORT", "8091"))
    host = os.environ.get("HOST", "0.0.0.0")
    app = create_app(
        system=System(),
        wire=MavsdkWire(),
        address=address,
        vehicle_kind="mavsdk",
    )
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
