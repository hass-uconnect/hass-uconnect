"""Select for Uconnect integration."""

from __future__ import annotations
import logging

from homeassistant.core import HomeAssistant
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

from py_uconnect.client import Vehicle
from py_uconnect.api import (
    CHARGING_LEVELS,
    CHARGING_LEVEL_ONE,
    CHARGING_LEVEL_TWO,
    CHARGING_LEVEL_THREE,
    CHARGING_LEVEL_FOUR,
    CHARGING_LEVEL_FIVE,
)
from py_uconnect.command import *

from .const import DOMAIN, CONF_ADD_COMMAND_ENTITIES
from .coordinator import UconnectDataUpdateCoordinator
from .entity import UconnectEntity

CHARGING_LEVEL_NAMES = [x.name for x in CHARGING_LEVELS]

ICONS = {
    CHARGING_LEVEL_ONE.name: "mdi:battery-charging-20",
    CHARGING_LEVEL_TWO.name: "mdi:battery-charging-40",
    CHARGING_LEVEL_THREE.name: "mdi:battery-charging-60",
    CHARGING_LEVEL_FOUR.name: "mdi:battery-charging-80",
    CHARGING_LEVEL_FIVE.name: "mdi:battery-charging-100",
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    # Do not add entities if not configured
    if not config_entry.options.get(CONF_ADD_COMMAND_ENTITIES):
        return

    coordinator: UconnectDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.unique_id
    ]
    entities: list[UconnectSelectSetChargingLevel] = []
    for vehicle in coordinator.client.vehicles.values():
        if getattr(vehicle, "charging_level_preference", None) is not None:
            entities.append(UconnectSelectSetChargingLevel(coordinator, vehicle))

    async_add_entities(entities)
    return True


class UconnectSelectSetChargingLevel(SelectEntity, UconnectEntity):
    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
    ):
        UconnectEntity.__init__(self, coordinator, vehicle)

        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_charging_level_preference"
        self._attr_name = (
            f"{vehicle.make} {vehicle.nickname or vehicle.model} Charging Level Pref"
        )

    @property
    def icon(self):
        return ICONS.get(
            self.vehicle.charging_level_preference, "mdi:battery-charging"
        )

    @property
    def options(self):
        return CHARGING_LEVEL_NAMES

    @property
    def current_option(self):
        return self.vehicle.charging_level_preference

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.async_set_charging_level(self.vehicle.vin, option)
        except Exception as err:
            _LOGGER.error(
                "Failed to set charging level to %s: %s", option, err
            )
            raise HomeAssistantError(f"Failed to set charging level: {err}") from err
