"""Battery and return-to-home planning rules.

PLACEHOLDER RATES
-----------------
``capacity_wh`` and ``wh_per_km`` are not measurements, flight logs, or
manufacturer figures. They exist so the go / no-go rule has numbers a test
can pin down. Replace them with the airframe's own capacity and cruise
draw before using the planner against a real vehicle.

The rule, given those inputs:

1. Refuse when the remaining percentage is below ``min_start_percent``.
2. Available energy is ``capacity_wh * remaining_percent / 100``.
3. Survey energy is ``path_length_km * wh_per_km``. The path length includes
   the legs between transects and the departure from home. It does not
   include the return.
4. Return energy is ``rth_safety_factor * farthest_home_km * wh_per_km``.
   The farthest waypoint is the abort case: a return from the worst point
   on the survey, not only from the final waypoint. Unused remainder of the
   survey is not credited back.
5. A landing reserve of ``landing_reserve_percent`` of the pack is held back
   and is not available for the survey or the return.
6. Launch is allowed only when available energy covers survey + return + reserve.
"""

from __future__ import annotations

from dataclasses import dataclass

from mission_planner.geometry import GeoPoint, farthest_from_m, path_length_m

# Placeholder pack and cruise draw. Not a measured vehicle.
DEFAULT_CAPACITY_WH = 100.0
DEFAULT_WH_PER_KM = 20.0
DEFAULT_MIN_START_PERCENT = 30.0
DEFAULT_LANDING_RESERVE_PERCENT = 20.0
DEFAULT_RTH_SAFETY_FACTOR = 1.2

PLACEHOLDER_NOTE = (
    "Placeholder energy model. capacity_wh and wh_per_km are not measurements; "
    "replace them with the airframe's own figures before a real flight."
)


@dataclass(frozen=True)
class EnergyModel:
    """Planning inputs. The two rates are placeholders, not a performance claim."""

    capacity_wh: float = DEFAULT_CAPACITY_WH
    wh_per_km: float = DEFAULT_WH_PER_KM
    min_start_percent: float = DEFAULT_MIN_START_PERCENT
    landing_reserve_percent: float = DEFAULT_LANDING_RESERVE_PERCENT
    rth_safety_factor: float = DEFAULT_RTH_SAFETY_FACTOR

    @property
    def placeholder(self) -> bool:
        return True


@dataclass(frozen=True)
class EnergyDecision:
    allowed: bool
    reason: str
    remaining_percent: float
    available_wh: float
    mission_wh: float
    rth_wh: float
    reserve_wh: float
    required_wh: float
    distance_m: float
    farthest_home_m: float
    placeholder: bool = True


def check_model(model: EnergyModel) -> None:
    if model.capacity_wh <= 0 or model.wh_per_km <= 0:
        raise ValueError("capacity_wh and wh_per_km must be positive")
    if not 0 <= model.min_start_percent <= 100:
        raise ValueError("min_start_percent must be between 0 and 100")
    if not 0 <= model.landing_reserve_percent <= 100:
        raise ValueError("landing_reserve_percent must be between 0 and 100")
    if model.rth_safety_factor < 1:
        raise ValueError("rth_safety_factor must be at least 1")


def evaluate_energy(
    distance_m: float,
    farthest_home_m: float,
    remaining_percent: float,
    model: EnergyModel | None = None,
) -> EnergyDecision:
    """Apply the placeholder budget to an already measured path."""
    model = model or EnergyModel()
    check_model(model)
    if distance_m < 0 or farthest_home_m < 0:
        raise ValueError("distances must be zero or positive")
    if not 0 <= remaining_percent <= 100:
        raise ValueError("remaining percent must be between 0 and 100")

    available_wh = model.capacity_wh * remaining_percent / 100.0
    mission_wh = (distance_m / 1000.0) * model.wh_per_km
    rth_wh = model.rth_safety_factor * (farthest_home_m / 1000.0) * model.wh_per_km
    reserve_wh = model.capacity_wh * model.landing_reserve_percent / 100.0
    required_wh = mission_wh + rth_wh + reserve_wh

    if remaining_percent < model.min_start_percent:
        reason = (
            f"battery {remaining_percent:.0f}% is below the "
            f"{model.min_start_percent:.0f}% start minimum"
        )
        allowed = False
    elif available_wh + 1e-9 < required_wh:
        reason = (
            "not enough energy in the placeholder model to fly the survey "
            "and return from the farthest waypoint"
        )
        allowed = False
    else:
        reason = "placeholder model allows launch with a return-to-home reserve"
        allowed = True

    return EnergyDecision(
        allowed=allowed,
        reason=reason,
        remaining_percent=remaining_percent,
        available_wh=available_wh,
        mission_wh=mission_wh,
        rth_wh=rth_wh,
        reserve_wh=reserve_wh,
        required_wh=required_wh,
        distance_m=distance_m,
        farthest_home_m=farthest_home_m,
    )


def evaluate_path(
    waypoints: list[GeoPoint] | tuple[GeoPoint, ...],
    home: GeoPoint,
    remaining_percent: float,
    model: EnergyModel | None = None,
) -> EnergyDecision:
    return evaluate_energy(
        distance_m=path_length_m(waypoints),
        farthest_home_m=farthest_from_m(home, waypoints),
        remaining_percent=remaining_percent,
        model=model,
    )
