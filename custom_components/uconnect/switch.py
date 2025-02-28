"""Switches for Uconnect integration."""

from __future__ import annotations
from typing import Final, Callable

import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntityDescription,
    SwitchEntity,
)

from py_uconnect.client import Vehicle
from py_uconnect.command import *

from .const import DOMAIN, CONF_ADD_COMMAND_ENTITIES
from .coordinator import UconnectDataUpdateCoordinator
from .entity import UconnectEntity


@dataclass
class UconnectSwitchEntityDescription(SwitchEntityDescription):
    """A class that describes custom switch entities."""

    command_on: Command = None
    command_off: Command = None
    on_icon: str | None = None
    off_icon: str | None = None
    is_on: Callable[[Vehicle], bool] | None = None


SWITCH_DESCRIPTIONS: Final[tuple[UconnectSwitchEntityDescription, ...]] = (
    UconnectSwitchEntityDescription(
        key="switch_engine",
        name="Engine",
        on_icon="mdi:engine",
        command_on=COMMAND_ENGINE_ON,
        command_off=COMMAND_ENGINE_OFF,
        is_on=lambda x: getattr(x, "ignition_on", None),
        device_class=SwitchDeviceClass.SWITCH,
    ),
    UconnectSwitchEntityDescription(
        key="switch_precondition",
        name="Precondition",
        on_icon="mdi:air-conditioner",
        command_on=COMMAND_PRECOND_ON,
        command_off=COMMAND_PRECOND_OFF,
        device_class=SwitchDeviceClass.SWITCH,
    ),
    UconnectSwitchEntityDescription(
        key="switch_hvac",
        name="HVAC",
        on_icon="mdi:hvac",
        command_on=COMMAND_HVAC_ON,
        command_off=COMMAND_HVAC_OFF,
        device_class=SwitchDeviceClass.SWITCH,
    ),
    UconnectSwitchEntityDescription(
        key="switch_comfort",
        name="Comfort",
        on_icon="mdi:air-conditioner",
        command_on=COMMAND_COMFORT_ON,
        command_off=COMMAND_COMFORT_OFF,
        device_class=SwitchDeviceClass.SWITCH,
    ),
    UconnectSwitchEntityDescription(
        key="switch_charging",
        name="Charging",
        on_icon="mdi:battery-charging",
        off_icon="mdi:battery-alert",
        command_on=COMMAND_CHARGE,
        is_on=lambda x: getattr(x, "charging", None),
        device_class=SwitchDeviceClass.SWITCH,
    ),
    UconnectSwitchEntityDescription(
        key="switch_trunk",
        name="Lock Trunk",
        on_icon="mdi:car-back",
        off_icon="mdi:car-back",
        command_on=COMMAND_TRUNK_LOCK,
        command_off=COMMAND_TRUNK_UNLOCK,
        device_class=SwitchDeviceClass.SWITCH,
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
    entities: list[UconnectSwitch] = []

    for vehicle in coordinator.client.vehicles.values():
        for description in SWITCH_DESCRIPTIONS:
            if (
                description.command_on is not None
                and description.command_on.name in vehicle.supported_commands
            ) or (
                description.command_off is not None
                and description.command_off.name in vehicle.supported_commands
            ):
                entities.append(UconnectSwitch(coordinator, description, vehicle))

    async_add_entities(entities)
    return True


class UconnectSwitch(SwitchEntity, UconnectEntity):
    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        description: UconnectSwitchEntityDescription,
        vehicle: Vehicle,
    ):
        UconnectEntity.__init__(self, coordinator, vehicle)

        self.entity_description: UconnectSwitchEntityDescription = description
        self._attr_name = f"{vehicle.make} {
            vehicle.nickname or vehicle.model} {description.name}"
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_{description.key}"

    @property
    def icon(self):
        if self.is_on:
            return self.entity_description.on_icon
        else:
            return self.entity_description.off_icon or self.entity_description.on_icon

    @property
    def is_on(self):
        if self.entity_description.is_on is not None:
            return self.entity_description.is_on(self.vehicle)

        return None

    async def async_turn_on(self, **kwargs):
        if self.entity_description.command_on is None:
            return

        await self.coordinator.async_command(
            self.vehicle.vin, self.entity_description.command_on
        )

    async def async_turn_off(self, **kwargs):
        if self.entity_description.command_off is None:
            return

        await self.coordinator.async_command(
            self.vehicle.vin, self.entity_description.command_off
        )
