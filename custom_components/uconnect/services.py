from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import ServiceCall, callback, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry

from py_uconnect.command import *

from .const import DOMAIN
from .coordinator import UconnectDataUpdateCoordinator

SERVICE_UPDATE = "update"

SERVICE_ENGINE_ON = "engine_on"
SERVICE_ENGINE_OFF = "engine_off"
SERVICE_COMFORT_ON = "comfort_on"
SERVICE_COMFORT_OFF = "comfort_off"
SERVICE_HVAC_ON = "hvac_on"
SERVICE_HVAC_OFF = "hvac_off"
SERVICE_PRECOND_ON = "precond_on"
SERVICE_PRECOND_OFF = "precond_off"
SERVICE_LIGHTS_HORN = "lights_horn"
SERVICE_LIGHTS = "lights"
SERVICE_DOORS_UNLOCK = "doors_unlock"
SERVICE_DOORS_LOCK = "doors_lock"
SERVICE_TRUNK_UNLOCK = "trunk_unlock"
SERVICE_TRUNK_LOCK = "trunk_lock"
SERVICE_LIFTGATE_UNLOCK = "liftgate_unlock"
SERVICE_LIFTGATE_LOCK = "liftgate_lock"
SERVICE_CHARGE = "charge_now"
SERVICE_DEEP_REFRESH = "deep_refresh"
SERVICE_REFRESH_LOCATION = "refresh_location"

SUPPORTED_SERVICES = [
    SERVICE_UPDATE,
    SERVICE_ENGINE_ON,
    SERVICE_ENGINE_OFF,
    SERVICE_COMFORT_ON,
    SERVICE_COMFORT_OFF,
    SERVICE_HVAC_ON,
    SERVICE_HVAC_OFF,
    SERVICE_PRECOND_ON,
    SERVICE_PRECOND_OFF,
    SERVICE_LIGHTS_HORN,
    SERVICE_LIGHTS,
    SERVICE_DOORS_UNLOCK,
    SERVICE_DOORS_LOCK,
    SERVICE_TRUNK_UNLOCK,
    SERVICE_TRUNK_LOCK,
    SERVICE_LIFTGATE_UNLOCK,
    SERVICE_LIFTGATE_LOCK,
    SERVICE_CHARGE,
    SERVICE_DEEP_REFRESH,
    SERVICE_REFRESH_LOCATION,
]

SERVICES_COMMANDS: dict[str, Command] = {
    SERVICE_ENGINE_ON: COMMAND_ENGINE_ON,
    SERVICE_ENGINE_OFF: COMMAND_ENGINE_OFF,
    SERVICE_COMFORT_ON: COMMAND_COMFORT_ON,
    SERVICE_COMFORT_OFF: COMMAND_COMFORT_OFF,
    SERVICE_HVAC_ON: COMMAND_HVAC_ON,
    SERVICE_HVAC_OFF: COMMAND_HVAC_OFF,
    SERVICE_PRECOND_ON: COMMAND_PRECOND_ON,
    SERVICE_PRECOND_OFF: COMMAND_PRECOND_OFF,
    SERVICE_LIGHTS_HORN: COMMAND_LIGHTS_HORN,
    SERVICE_LIGHTS: COMMAND_LIGHTS,
    SERVICE_DOORS_UNLOCK: COMMAND_DOORS_UNLOCK,
    SERVICE_DOORS_LOCK: COMMAND_DOORS_LOCK,
    SERVICE_TRUNK_UNLOCK: COMMAND_TRUNK_UNLOCK,
    SERVICE_TRUNK_LOCK: COMMAND_TRUNK_LOCK,
    SERVICE_LIFTGATE_UNLOCK: COMMAND_LIFTGATE_UNLOCK,
    SERVICE_LIFTGATE_LOCK: COMMAND_LIFTGATE_LOCK,
    SERVICE_CHARGE: COMMAND_CHARGE,
    SERVICE_DEEP_REFRESH: COMMAND_DEEP_REFRESH,
    SERVICE_REFRESH_LOCATION: COMMAND_REFRESH_LOCATION,
}


@callback
def async_setup_services(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up services for Uconnect"""

    async def async_call_service(call: ServiceCall):
        coordinator: UconnectDataUpdateCoordinator = _get_coordinator_from_device(
            hass, call
        )
        vin = _get_vin_from_device(hass, call)

        if call.service != SERVICE_UPDATE:
            cmd = SERVICES_COMMANDS[call.service]
            vehicle = coordinator.client.vehicles.get(vin)
            if vehicle is None:
                raise HomeAssistantError(f"Vehicle {vin} not found")
            if cmd.name not in vehicle.supported_commands:
                raise HomeAssistantError(f"Service {call.service} is not supported by this vehicle")

            await coordinator.async_command(vin, cmd)
        else:
            await coordinator.async_refresh()

    coordinator: UconnectDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.unique_id
    ]

    # Get a set of all supported commands from all cars
    supported_commands = set()
    for v in coordinator.client.vehicles.values():
        for cmd in v.supported_commands:
            if cmd in COMMANDS_BY_NAME:
                supported_commands.add(cmd)

    for service in SUPPORTED_SERVICES:
        # Create the service only if it's supported by at least one car
        if (
            service == SERVICE_UPDATE
            or SERVICES_COMMANDS[service].name in supported_commands
        ):
            hass.services.async_register(DOMAIN, service, async_call_service)

    return True


@callback
def async_unload_services(hass) -> None:
    for service in SUPPORTED_SERVICES:
        hass.services.async_remove(DOMAIN, service)


def _get_vin_from_device(hass: HomeAssistant, call: ServiceCall) -> str:
    coordinators = list(hass.data[DOMAIN].keys())

    if len(coordinators) == 1:
        coordinator: UconnectDataUpdateCoordinator = hass.data[DOMAIN][coordinators[0]]
        vehicles = coordinator.client.get_vehicles()
        if len(vehicles) == 1:
            return list(vehicles.keys())[0]

    device_entry = device_registry.async_get(hass).async_get(call.data[ATTR_DEVICE_ID])
    if device_entry is None:
        raise ValueError(f"Device not found: {call.data.get(ATTR_DEVICE_ID)}")

    for entry in device_entry.identifiers:
        if entry[0] == DOMAIN:
            return entry[1]

    raise ValueError(f"No VIN found for device: {call.data.get(ATTR_DEVICE_ID)}")


def _get_coordinator_from_device(
    hass: HomeAssistant, call: ServiceCall
) -> UconnectDataUpdateCoordinator:
    coordinators = list(hass.data[DOMAIN].keys())

    if len(coordinators) == 1:
        return hass.data[DOMAIN][coordinators[0]]

    device_entry = device_registry.async_get(hass).async_get(call.data[ATTR_DEVICE_ID])
    if device_entry is None:
        raise ValueError(f"Device not found: {call.data.get(ATTR_DEVICE_ID)}")

    config_entry_id = next(
        (
            entry_id
            for entry_id in device_entry.config_entries
            if (entry := hass.config_entries.async_get_entry(entry_id))
            and entry.domain == DOMAIN
        ),
        None,
    )
    if config_entry_id is None:
        raise ValueError(f"No config entry found for device: {call.data.get(ATTR_DEVICE_ID)}")

    config_entry = hass.config_entries.async_get_entry(config_entry_id)
    if config_entry is None:
        raise ValueError(f"Config entry not found: {config_entry_id}")
    return hass.data[DOMAIN][config_entry.unique_id]
