"""Capabilities of the SSDP vehicles, from their data"""

from __future__ import annotations

from stellantis_ssdp import Vehicle


def has_battery(vehicle: Vehicle) -> bool:
    """Whether the vehicle has a traction battery (electric or plug-in hybrid).

    The telemetry then has an electric energy, but its values can be missing
    at times, e.g. the state of charge of a plug-in hybrid.
    """

    telemetry = vehicle.raw_telemetry or {}
    energies = telemetry.get("vehicle", {}).get("energies")
    if isinstance(energies, list) and any(
        isinstance(e, dict) and str(e.get("type", "")).lower() == "electric"
        for e in energies
    ):
        return True

    return any(
        v is not None
        for v in (
            vehicle.state_of_charge,
            vehicle.range_electric,
            vehicle.charging_status,
            vehicle.plugged_in,
        )
    )
