"""Actions (services) of the Uconnect integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.const import ATTR_DEVICE_ID, UnitOfTemperature
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from py_uconnect import TemperatureUnit, Vehicle, hvac_params
from py_uconnect.command import (
    COMMAND_CABIN_VENTILATION,
    COMMAND_CHARGE,
    COMMAND_CHARGE_V4,
    COMMAND_COMFORT_OFF,
    COMMAND_COMFORT_ON,
    COMMAND_DEEP_REFRESH,
    COMMAND_DEEP_REFRESH_V2,
    COMMAND_DOORS_LOCK,
    COMMAND_DOORS_UNLOCK,
    COMMAND_ENGINE_OFF,
    COMMAND_ENGINE_ON,
    COMMAND_HVAC_OFF,
    COMMAND_HVAC_ON,
    COMMAND_LIFTGATE_LOCK,
    COMMAND_LIFTGATE_UNLOCK,
    COMMAND_LIGHTS,
    COMMAND_LIGHTS_HORN,
    COMMAND_PRECOND_OFF,
    COMMAND_PRECOND_ON,
    COMMAND_REFRESH_LOCATION,
    COMMAND_TRUNK_LOCK,
    COMMAND_TRUNK_UNLOCK,
    SCHEDULE_ENDPOINTS,
    Command,
    schedule_endpoint,
)
import voluptuous as vol

from .const import DOMAIN
from .coordinator import UconnectDataUpdateCoordinator, async_get_coordinators

SERVICE_UPDATE = "update"
SERVICE_SET_CHARGE_SCHEDULE = "set_charge_schedule"
SERVICE_SEND_DESTINATION = "send_destination"

ATTR_TEMPERATURE = "temperature"
ATTR_SCHEDULE = "schedule"
ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"
ATTR_NAME = "name"

# Service of a vehicle that allows setting the climate target temperature
SERVICE_HVAC_TARGET_TEMP = "ROHVACTMP"
# Service of a vehicle that allows sending destinations
SERVICE_SDV = "SDV"

BASE_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_DEVICE_ID): cv.string}, extra=vol.ALLOW_EXTRA
)

Handler = Callable[
    [HomeAssistant, UconnectDataUpdateCoordinator, Vehicle, ServiceCall],
    Awaitable[None],
]


@dataclass(frozen=True)
class UconnectService:
    """An action and the vehicles supporting it"""

    handler: Handler
    # Whether a vehicle supports the action, None if all do
    supported: Callable[[Vehicle], bool] | None = None
    schema: vol.Schema = field(default_factory=lambda: BASE_SCHEMA)


def _command_handler(cmd: Command) -> Handler:
    async def handler(
        hass: HomeAssistant,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
        call: ServiceCall,
    ) -> None:
        await coordinator.async_command(vehicle.vin, cmd)

    return handler


def _command_service(cmd: Command, *services: str) -> UconnectService:
    """An action sending a command, supported by the vehicles having one of the
    given services enabled (by default the ones enabling the command)"""

    if services:
        return UconnectService(
            _command_handler(cmd),
            lambda v: any(s in v.enabled_services for s in services),
        )

    return UconnectService(_command_handler(cmd), lambda v: v.supports(cmd))


async def _handle_update(
    hass: HomeAssistant,
    coordinator: UconnectDataUpdateCoordinator,
    vehicle: Vehicle,
    call: ServiceCall,
) -> None:
    await coordinator.async_refresh()


async def _handle_hvac_on(
    hass: HomeAssistant,
    coordinator: UconnectDataUpdateCoordinator,
    vehicle: Vehicle,
    call: ServiceCall,
) -> None:
    params = None

    if (temperature := call.data.get(ATTR_TEMPERATURE)) is not None:
        if SERVICE_HVAC_TARGET_TEMP not in vehicle.enabled_services:
            raise ServiceValidationError(
                f"Vehicle {vehicle.vin} does not support setting the temperature"
            )

        unit = (
            TemperatureUnit.FAHRENHEIT
            if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT
            else TemperatureUnit.CELSIUS
        )
        params = hvac_params(temperature, unit)

    await coordinator.async_command(vehicle.vin, COMMAND_HVAC_ON, params)


def _parse_schedules(value: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Return the schedules and the schedule command from the action data.

    Accepts a list of schedules, or an object holding them in one of the
    schedule fields of the API (e.g. ``chargeSchedulesV3``) with an optional
    ``command``, as returned by the vehicle.
    """

    if isinstance(value, list):
        return value, None

    if isinstance(value, dict):
        for ep in SCHEDULE_ENDPOINTS:
            if isinstance(value.get(ep.field), list):
                command = value.get("command")
                return value[ep.field], command if isinstance(command, str) else None

    fields = ", ".join(dict.fromkeys(ep.field for ep in SCHEDULE_ENDPOINTS))
    raise ServiceValidationError(
        f"schedule must be a list of schedules or an object with one of: {fields}"
    )


async def _handle_set_charge_schedule(
    hass: HomeAssistant,
    coordinator: UconnectDataUpdateCoordinator,
    vehicle: Vehicle,
    call: ServiceCall,
) -> None:
    schedules, command = _parse_schedules(call.data[ATTR_SCHEDULE])
    await coordinator.async_set_charge_schedules(vehicle.vin, schedules, command)


async def _handle_send_destination(
    hass: HomeAssistant,
    coordinator: UconnectDataUpdateCoordinator,
    vehicle: Vehicle,
    call: ServiceCall,
) -> None:
    await coordinator.async_send_destination(
        vehicle.vin,
        call.data[ATTR_LATITUDE],
        call.data[ATTR_LONGITUDE],
        call.data.get(ATTR_NAME),
    )


SERVICES: dict[str, UconnectService] = {
    SERVICE_UPDATE: UconnectService(_handle_update),
    "engine_on": _command_service(COMMAND_ENGINE_ON),
    "engine_off": _command_service(COMMAND_ENGINE_OFF),
    "comfort_on": _command_service(COMMAND_COMFORT_ON),
    "comfort_off": _command_service(COMMAND_COMFORT_OFF),
    "hvac_on": UconnectService(
        _handle_hvac_on,
        lambda v: v.supports(COMMAND_HVAC_ON),
        BASE_SCHEMA.extend({vol.Optional(ATTR_TEMPERATURE): vol.Coerce(float)}),
    ),
    "hvac_off": _command_service(COMMAND_HVAC_OFF),
    "precond_on": _command_service(COMMAND_PRECOND_ON),
    "precond_off": _command_service(COMMAND_PRECOND_OFF),
    "lights_horn": _command_service(COMMAND_LIGHTS_HORN),
    "lights": _command_service(COMMAND_LIGHTS),
    "doors_unlock": _command_service(COMMAND_DOORS_UNLOCK),
    "doors_lock": _command_service(COMMAND_DOORS_LOCK),
    "trunk_unlock": _command_service(COMMAND_TRUNK_UNLOCK),
    "trunk_lock": _command_service(COMMAND_TRUNK_LOCK),
    "liftgate_unlock": _command_service(COMMAND_LIFTGATE_UNLOCK),
    "liftgate_lock": _command_service(COMMAND_LIFTGATE_LOCK),
    "cabin_ventilation": _command_service(COMMAND_CABIN_VENTILATION),
    # charge_now and deep_refresh pick the variant fitting the vehicle, the
    # *_v4/*_v2 actions force the newer one
    "charge_now": _command_service(COMMAND_CHARGE),
    "charge_now_v4": _command_service(COMMAND_CHARGE_V4, "CNOW2"),
    "deep_refresh": _command_service(COMMAND_DEEP_REFRESH),
    "deep_refresh_v2": _command_service(COMMAND_DEEP_REFRESH_V2, "DEEPREFRESH2"),
    "refresh_location": _command_service(COMMAND_REFRESH_LOCATION),
    SERVICE_SET_CHARGE_SCHEDULE: UconnectService(
        _handle_set_charge_schedule,
        lambda v: schedule_endpoint(v.enabled_services) is not None,
        BASE_SCHEMA.extend({vol.Required(ATTR_SCHEDULE): vol.Any(dict, list)}),
    ),
    SERVICE_SEND_DESTINATION: UconnectService(
        _handle_send_destination,
        lambda v: SERVICE_SDV in v.enabled_services,
        BASE_SCHEMA.extend(
            {
                vol.Required(ATTR_LATITUDE): cv.latitude,
                vol.Required(ATTR_LONGITUDE): cv.longitude,
                vol.Optional(ATTR_NAME): cv.string,
            }
        ),
    ),
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions supported by at least one vehicle and remove the
    ones no vehicle supports anymore."""

    async def handle(call: ServiceCall) -> None:
        await _async_handle_service(hass, call)

    vehicles = [
        v for c in async_get_coordinators(hass) for v in c.client.vehicles.values()
    ]

    for name, service in SERVICES.items():
        supported = service.supported is None or any(
            service.supported(v) for v in vehicles
        )
        registered = hass.services.has_service(DOMAIN, name)

        if supported and not registered:
            hass.services.async_register(DOMAIN, name, handle, schema=service.schema)
        elif not supported and registered:
            hass.services.async_remove(DOMAIN, name)


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove all actions."""

    for name in SERVICES:
        if hass.services.has_service(DOMAIN, name):
            hass.services.async_remove(DOMAIN, name)


async def _async_handle_service(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator, vin = _resolve_target(hass, call)

    vehicle = coordinator.client.vehicles.get(vin)
    if vehicle is None:
        raise ServiceValidationError(f"Vehicle {vin} not found")

    service = SERVICES[call.service]
    if service.supported is not None and not service.supported(vehicle):
        raise ServiceValidationError(
            f"Action {call.service} is not supported by vehicle {vin}"
        )

    await service.handler(hass, coordinator, vehicle, call)


def _resolve_target(
    hass: HomeAssistant, call: ServiceCall
) -> tuple[UconnectDataUpdateCoordinator, str]:
    """Return the coordinator and the VIN of the vehicle targeted by an action.

    The device can be omitted if there is a single vehicle.
    """

    coordinators = async_get_coordinators(hass)

    device_id = call.data.get(ATTR_DEVICE_ID)
    if device_id is None:
        if len(coordinators) == 1 and len(coordinators[0].client.vehicles) == 1:
            return coordinators[0], next(iter(coordinators[0].client.vehicles))
        raise ServiceValidationError("A vehicle must be selected")

    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(f"Device not found: {device_id}")

    vin = next((i[1] for i in device.identifiers if i[0] == DOMAIN), None)
    if vin is None:
        raise ServiceValidationError(f"Device {device_id} is not a Uconnect vehicle")

    # Newer Home Assistant versions have a single config entry per device
    if hasattr(device, "config_entry_id"):
        entry_ids = {device.config_entry_id}
    else:
        entry_ids = set(device.config_entries)

    for coordinator in coordinators:
        if (
            coordinator.config_entry.entry_id in entry_ids
            and vin in coordinator.client.vehicles
        ):
            return coordinator, vin

    raise ServiceValidationError(f"Vehicle {vin} is not loaded")
