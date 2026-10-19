"""Buttons for Uconnect integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from py_uconnect import Vehicle
from py_uconnect.command import (
    COMMAND_CHARGE,
    COMMAND_DEEP_REFRESH,
    COMMAND_LIGHTS,
    COMMAND_LIGHTS_HORN,
    COMMAND_REFRESH_LOCATION,
    Command,
)

from .const import CONF_ADD_COMMAND_ENTITIES, DOMAIN
from .coordinator import UconnectConfigEntry, UconnectDataUpdateCoordinator
from .entity import UconnectEntity, should_add, vehicle_name


@dataclass(frozen=True, kw_only=True)
class UconnectButtonEntityDescription(ButtonEntityDescription):
    """A class that describes custom switch entities."""

    command: Command | None = None


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
    config_entry: UconnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    entities: list[ButtonEntity] = []

    def add(vin: str, key: str, supported: bool) -> bool:
        return should_add(hass, Platform.BUTTON, f"{DOMAIN}_{vin}_{key}", supported)

    # EV-specific buttons (always available), for the vehicles which get an
    # extrapolated SOC sensor. The sensor platform may not be set up yet, so
    # the condition is checked rather than the sensors.
    for vehicle in coordinator.client.vehicles.values():
        if add(
            vehicle.vin, "reset_battery_learning", vehicle.state_of_charge is not None
        ):
            entities.append(UconnectResetLearningButton(coordinator, vehicle))

    # Command entities (gated behind option)
    if config_entry.options.get(CONF_ADD_COMMAND_ENTITIES):
        for vehicle in coordinator.client.vehicles.values():
            entities.append(UconnectButtonUpdate(coordinator, vehicle))

            for description in BUTTON_DESCRIPTIONS:
                if description.command is not None and add(
                    vehicle.vin,
                    description.key,
                    vehicle.supports(description.command),
                ):
                    entities.append(UconnectButton(coordinator, description, vehicle))

    async_add_entities(entities)


class UconnectButton(ButtonEntity, UconnectEntity):
    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        description: UconnectButtonEntityDescription,
        vehicle: Vehicle,
    ):
        UconnectEntity.__init__(self, coordinator, vehicle)

        self.entity_description: UconnectButtonEntityDescription = description
        self._attr_name = f"{vehicle_name(vehicle)} {description.name}"
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

        self._attr_name = f"{vehicle_name(vehicle)} Update Data"
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_update"

    @property
    def icon(self):
        return "mdi:update"

    async def async_press(self, **kwargs):
        await self.coordinator.async_refresh()


class UconnectResetLearningButton(ButtonEntity, UconnectEntity):
    """Button to reset learned battery charging and drain parameters."""

    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
    ):
        UconnectEntity.__init__(self, coordinator, vehicle)

        self._attr_name = f"{vehicle_name(vehicle)} Reset Battery Learning"
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_reset_battery_learning"
        self._attr_icon = "mdi:head-sync-outline"

    async def async_press(self, **kwargs):
        sensor = self.coordinator.extrapolated_soc_sensors.get(self._vin)
        if sensor is not None:
            sensor.reset_learning()
