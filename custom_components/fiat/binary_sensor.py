"""Sensor for Fiat integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Final

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from pyfiat.client import Vehicle

from .const import DOMAIN
from .coordinator import FiatDataUpdateCoordinator
from .entity import FiatEntity

_LOGGER = logging.getLogger(__name__)


@dataclass
class FiatBinarySensorEntityDescription(BinarySensorEntityDescription):
    """A class that describes custom binary sensor entities."""

    is_on: Callable[[Vehicle], bool] | None = None
    on_icon: str | None = None
    off_icon: str | None = None


SENSOR_DESCRIPTIONS: Final[tuple[FiatBinarySensorEntityDescription, ...]] = (
    FiatBinarySensorEntityDescription(
        key="ignition_on",
        name="Ignition",
        is_on=lambda vehicle: vehicle.ignition_on,
        on_icon="mdi:engine",
        off_icon="mdi:engine-off",
    ),
    FiatBinarySensorEntityDescription(
        key="door_driver_locked",
        name="Driver door is locked",
        is_on=lambda vehicle: not vehicle.doors['DRIVER'].locked,
        on_icon="mdi:car-door",
        off_icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    FiatBinarySensorEntityDescription(
        key="door_passenger_locked",
        name="Passenger door is locked",
        is_on=lambda vehicle: not vehicle.doors['PASSENGER'].locked,
        on_icon="mdi:car-door",
        off_icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    FiatBinarySensorEntityDescription(
        key="door_rear_left_locked",
        name="Rear left door is locked",
        is_on=lambda vehicle: not vehicle.doors['REAR_LEFT'].locked,
        on_icon="mdi:car-door",
        off_icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    FiatBinarySensorEntityDescription(
        key="door_rear_right_locked",
        name="Rear right door is locked",
        is_on=lambda vehicle: not vehicle.doors['REAR_RIGHT'].locked,
        on_icon="mdi:car-door",
        off_icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    FiatBinarySensorEntityDescription(
        key="trunk_locked",
        name="Trunk is locked",
        is_on=lambda vehicle: not vehicle.trunk_locked,
        on_icon="mdi:car-back",
        off_icon="mdi:car-back",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    FiatBinarySensorEntityDescription(
        key="driver_window_closed",
        name="Driver window is closed",
        is_on=lambda vehicle: not vehicle.windows['DRIVER'].closed,
        on_icon="mdi:car-door",
        off_icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    FiatBinarySensorEntityDescription(
        key="passenger_window_closed",
        name="Passenger window is closed",
        is_on=lambda vehicle: not vehicle.windows['PASSENGER'].closed,
        on_icon="mdi:car-door",
        off_icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    FiatBinarySensorEntityDescription(
        key="charger_is_plugged_in",
        name="EV charger is plugged in",
        is_on=lambda vehicle: vehicle.plugged_in,
        device_class=BinarySensorDeviceClass.PLUG,
    ),
    FiatBinarySensorEntityDescription(
        key="tire_pressure_front_left_ok",
        name="Tire Pressure - Front Left is ok",
        is_on=lambda vehicle: not vehicle.wheels['FL'].status_normal,
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    FiatBinarySensorEntityDescription(
        key="tire_pressure_front_right_ok",
        name="Tire Pressure - Front Right is ok",
        is_on=lambda vehicle: not vehicle.wheels['FR'].status_normal,
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    FiatBinarySensorEntityDescription(
        key="tire_pressure_rear_right_ok",
        name="Tire Pressure - Rear Right is ok",
        is_on=lambda vehicle: not vehicle.wheels['RR'].status_normal,
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    FiatBinarySensorEntityDescription(
        key="tire_pressure_rear_left_ok",
        name="Tire Pressure - Rear Left is ok",
        is_on=lambda vehicle: not vehicle.wheels['RL'].status_normal,
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary_sensor platform."""

    coordinator: FiatDataUpdateCoordinator = hass.data[DOMAIN][config_entry.unique_id]
    entities: list[FiatBinarySensor] = []

    for vehicle in coordinator.client.vehicles.values():
        for description in SENSOR_DESCRIPTIONS:
            if description.is_on is not None and description.is_on(vehicle) is not None:
                entities.append(
                    FiatBinarySensor(
                        coordinator, description, vehicle)
                )

    async_add_entities(entities)

    return True


class FiatBinarySensor(BinarySensorEntity, FiatEntity):
    """Fiat binary sensor class."""

    def __init__(
        self,
        coordinator: FiatDataUpdateCoordinator,
        description: FiatBinarySensorEntityDescription,
        vehicle: Vehicle,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle)
        self.entity_description: FiatBinarySensorEntityDescription = description
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_{description.key}"
        self._attr_name = f"{vehicle.make} {
            vehicle.nickname or vehicle.model} {description.name}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""

        if self.entity_description.is_on is not None:
            return self.entity_description.is_on(self.vehicle)

        return None

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""

        if (
            self.entity_description.on_icon == self.entity_description.off_icon
        ) is None:
            return BinarySensorEntity.icon

        return (
            self.entity_description.on_icon
            if self.is_on
            else self.entity_description.off_icon
        )
