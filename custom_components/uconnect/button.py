"""Buttons for Uconnect integration."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Final

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntityDescription,
    ButtonEntity,
)

from py_uconnect.client import Vehicle
from py_uconnect.command import *

from .const import DOMAIN, CONF_ADD_COMMAND_ENTITIES
from .coordinator import UconnectDataUpdateCoordinator
from .entity import UconnectEntity


@dataclass
class UconnectButtonEntityDescription(ButtonEntityDescription):
    """A class that describes custom switch entities."""

    command: Command = None


BUTTON_DESCRIPTIONS: Final[tuple[UconnectButtonEntityDescription, ...]] = (
    UconnectButtonEntityDescription(
        key="button_location",
        name="Refresh Location",
        icon="mdi:crosshairs-gps",
        command=COMMAND_REFRESH_LOCATION,
        device_class=ButtonDeviceClass.UPDATE,
    ),
    UconnectButtonEntityDescription(
        key="button_deep_refresh",
        name="Deep Refresh",
        icon="mdi:refresh",
        command=COMMAND_DEEP_REFRESH,
        device_class=ButtonDeviceClass.UPDATE,
    ),
    UconnectButtonEntityDescription(
        key="button_charge",
        name="Charge Now",
        icon="mdi:ev-station",
        command=COMMAND_CHARGE,
        device_class=ButtonDeviceClass.UPDATE,
    ),
    UconnectButtonEntityDescription(
        key="button_lights",
        name="Lights",
        icon="mdi:car-light-dimmed",
        command=COMMAND_LIGHTS,
        device_class=ButtonDeviceClass.UPDATE,
    ),
    UconnectButtonEntityDescription(
        key="button_lights_horn",
        name="Lights & Horn",
        icon="mdi:bugle",
        command=COMMAND_LIGHTS_HORN,
        device_class=ButtonDeviceClass.UPDATE,
    ),
)


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
    entities: list[UconnectButton] = []

    for vehicle in coordinator.client.vehicles.values():
        entities.append(UconnectButtonUpdate(coordinator, vehicle))

        for description in BUTTON_DESCRIPTIONS:
            if description.command.name in vehicle.supported_commands:
                entities.append(UconnectButton(coordinator, description, vehicle))

    async_add_entities(entities)
    return True


class UconnectButton(ButtonEntity, UconnectEntity):
    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        description: UconnectButtonEntityDescription,
        vehicle: Vehicle,
    ):
        UconnectEntity.__init__(self, coordinator, vehicle)

        self.entity_description: UconnectButtonEntityDescription = description
        self._attr_name = f"{vehicle.make} {
            vehicle.nickname or vehicle.model} {description.name}"
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_{description.key}"

    @property
    def icon(self):
        return self.entity_description.icon

    async def async_press(self, **kwargs):
        await self.coordinator.async_command(
            self.vehicle.vin, self.entity_description.command
        )


class UconnectButtonUpdate(ButtonEntity, UconnectEntity):
    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
    ):
        UconnectEntity.__init__(self, coordinator, vehicle)

        self._attr_name = f"{vehicle.make} {
            vehicle.nickname or vehicle.model} Update Data"
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_update"

    @property
    def icon(self):
        return "mdi:update"

    async def async_press(self, **kwargs):
        await self.coordinator.async_refresh()
