"""Switches for Uconnect integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Final

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from py_uconnect import Vehicle
from py_uconnect.command import (
    COMMAND_CHARGE,
    COMMAND_COMFORT_OFF,
    COMMAND_COMFORT_ON,
    COMMAND_ENGINE_OFF,
    COMMAND_ENGINE_ON,
    COMMAND_HVAC_OFF,
    COMMAND_HVAC_ON,
    COMMAND_PRECOND_OFF,
    COMMAND_PRECOND_ON,
    COMMAND_TRUNK_LOCK,
    COMMAND_TRUNK_UNLOCK,
    Command,
)

from .const import CONF_ADD_COMMAND_ENTITIES, DOMAIN
from .coordinator import UconnectConfigEntry, UconnectDataUpdateCoordinator
from .entity import UconnectEntity, should_add, vehicle_name

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class UconnectSwitchEntityDescription(SwitchEntityDescription):
    """A class that describes custom switch entities."""

    command_on: Command | None = None
    command_off: Command | None = None
    on_icon: str | None = None
    off_icon: str | None = None
    is_on: Callable[[Vehicle], bool | None] | None = None
    is_available: Callable[[Vehicle], bool] = lambda x: True


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
        is_on=lambda x: x.hvac_on,
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
        on_icon="mdi:lock",
        off_icon="mdi:lock-open",
        command_on=COMMAND_TRUNK_LOCK,
        command_off=COMMAND_TRUNK_UNLOCK,
        is_on=lambda x: x.trunk_locked,
        device_class=SwitchDeviceClass.SWITCH,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UconnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    # Do not add entities if not configured
    if not config_entry.options.get(CONF_ADD_COMMAND_ENTITIES):
        return

    coordinator = config_entry.runtime_data
    entities: list[UconnectSwitch] = []

    for vehicle in coordinator.client.vehicles.values():
        for description in SWITCH_DESCRIPTIONS:
            supported = description.is_available(vehicle) and any(
                cmd is not None and vehicle.supports(cmd)
                for cmd in (description.command_on, description.command_off)
            )
            if should_add(
                hass,
                Platform.SWITCH,
                f"{DOMAIN}_{vehicle.vin}_{description.key}",
                supported,
            ):
                entities.append(UconnectSwitch(coordinator, description, vehicle))

    async_add_entities(entities)


class UconnectSwitch(SwitchEntity, UconnectEntity):
    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        description: UconnectSwitchEntityDescription,
        vehicle: Vehicle,
    ):
        UconnectEntity.__init__(self, coordinator, vehicle)

        self.entity_description: UconnectSwitchEntityDescription = description
        self._attr_name = f"{vehicle_name(vehicle)} {description.name}"
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
            raise HomeAssistantError(
                f"{self.entity_description.name} cannot be turned on"
            )

        try:
            await self.coordinator.async_command(
                self.vehicle.vin, self.entity_description.command_on
            )
        except Exception as err:
            _LOGGER.error("Failed to turn on %s: %s", self.entity_description.key, err)
            raise HomeAssistantError(f"Failed to turn on: {err}") from err

    async def async_turn_off(self, **kwargs):
        if self.entity_description.command_off is None:
            raise HomeAssistantError(
                f"{self.entity_description.name} cannot be turned off"
            )

        try:
            await self.coordinator.async_command(
                self.vehicle.vin, self.entity_description.command_off
            )
        except Exception as err:
            _LOGGER.error("Failed to turn off %s: %s", self.entity_description.key, err)
            raise HomeAssistantError(f"Failed to turn off: {err}") from err
