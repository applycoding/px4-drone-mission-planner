"""Survey-grid mission planner for PX4.

The geometry, geofence, and energy checks are pure Python. A run controller
uploads the result through a MAVSDK-shaped vehicle. The default vehicle is
fake; PX4 SITL is an optional local Docker step.
"""

__version__ = "0.1.0"
