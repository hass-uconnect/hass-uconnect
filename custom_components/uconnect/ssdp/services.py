"""Actions (services) for the SSDP vehicles.

The actions are shared with the Uconnect vehicles (services.py): an action is
registered when a vehicle of either backend supports it, and runs the handler
of the backend of the target vehicle. This table only has the actions SSDP
vehicles support; the others are reported as not supported for them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from stellantis_ssdp import RemoteCommand, Vehicle, remote
import voluptuous as vol

from .coordinator import SsdpDataUpdateCoordinator
from .vehicle import has_battery

ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"
ATTR_NAME = "name"

# Schema of the actions only SSDP vehicles have
SSDP_BASE_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_DEVICE_ID): cv.string}, extra=vol.ALLOW_EXTRA
)

SsdpHandler = Callable[
    [HomeAssistant, SsdpDataUpdateCoordinator, Vehicle, ServiceCall],
    Awaitable[None],
]


@dataclass(frozen=True)
class SsdpService:
    """An action for SSDP vehicles"""

    handler: SsdpHandler
    # Whether a vehicle supports the action, None if all do
    supported: Callable[[SsdpDataUpdateCoordinator, Vehicle], bool] | None = None
    # Only for the actions Uconnect does not have: the others keep its schema
    schema: vol.Schema | None = None


def _enrolled(coordinator: SsdpDataUpdateCoordinator, vehicle: Vehicle) -> bool:
    """Remote commands need the one-time setup with an SMS code"""

    return coordinator.enrolled


def _command_service(
    command: Callable[[], RemoteCommand],
    supported: Callable[[Vehicle], bool] | None = None,
    schema: vol.Schema | None = None,
) -> SsdpService:
    async def handler(
        hass: HomeAssistant,
        coordinator: SsdpDataUpdateCoordinator,
        vehicle: Vehicle,
        call: ServiceCall,
    ) -> None:
        await coordinator.async_command(vehicle.vin, command())

    def is_supported(coordinator: SsdpDataUpdateCoordinator, vehicle: Vehicle) -> bool:
        return _enrolled(coordinator, vehicle) and (
            supported is None or supported(vehicle)
        )

    return SsdpService(handler, is_supported, schema)


async def _handle_update(
    hass: HomeAssistant,
    coordinator: SsdpDataUpdateCoordinator,
    vehicle: Vehicle,
    call: ServiceCall,
) -> None:
    await coordinator.async_refresh()


async def _handle_send_destination(
    hass: HomeAssistant,
    coordinator: SsdpDataUpdateCoordinator,
    vehicle: Vehicle,
    call: ServiceCall,
) -> None:
    await coordinator.async_command(
        vehicle.vin,
        remote.send_destination(
            call.data[ATTR_LATITUDE],
            call.data[ATTR_LONGITUDE],
            call.data.get(ATTR_NAME),
        ),
    )


SSDP_SERVICES: dict[str, SsdpService] = {
    "update": SsdpService(_handle_update),
    "engine_on": _command_service(lambda: remote.engine(True)),
    "engine_off": _command_service(lambda: remote.engine(False)),
    "precond_on": _command_service(lambda: remote.preconditioning(True)),
    "precond_off": _command_service(lambda: remote.preconditioning(False)),
    "lights": _command_service(remote.lights),
    # Uconnect has no action for the horn alone
    "horn": _command_service(remote.horn, schema=SSDP_BASE_SCHEMA),
    "doors_lock": _command_service(remote.lock_doors),
    "doors_unlock": _command_service(remote.unlock_doors),
    "charge_now": _command_service(lambda: remote.charge_now(True), has_battery),
    "deep_refresh": _command_service(remote.wakeup),
    "refresh_location": _command_service(remote.locate),
    "send_destination": SsdpService(_handle_send_destination, _enrolled),
}
