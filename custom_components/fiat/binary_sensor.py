"""Sensor for Fiat integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass
class FiatBinarySensorEntityDescription(BinarySensorEntityDescription):
    """A class that describes custom binary sensor entities."""

    is_on: Callable[[Vehicle], bool] | None = None
    postprocess: Callable[[bool], bool] | None = None
    on_icon: str | None = None
    off_icon: str | None = None


SENSOR_DESCRIPTIONS: Final[tuple[FiatBinarySensorEntityDescription, ...]] = (
    FiatBinarySensorEntityDescription(
        key="ignition_on",
        name="Ignition",
        on_icon="mdi:engine",
        off_icon="mdi:engine-off",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    FiatBinarySensorEntityDescription(
        key="ev_running",
        name="EV Running",
        on_icon="mdi:engine",
        off_icon="mdi:engine-off",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    FiatBinarySensorEntityDescription(
        key="door_driver_locked",
        name="Door Driver",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door-lock",
        off_icon="mdi:car-door-lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    FiatBinarySensorEntityDescription(
        key="door_passenger_locked",
        name="Door Passenger",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door-lock",
        off_icon="mdi:car-door-lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    FiatBinarySensorEntityDescription(
        key="door_rear_left_locked",
        name="Door Rear Left",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door-lock",
        off_icon="mdi:car-door-lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    FiatBinarySensorEntityDescription(
        key="door_rear_right_locked",
        name="Door Rear Right",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door-lock",
        off_icon="mdi:car-door-lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    FiatBinarySensorEntityDescription(
        key="trunk_locked",
        name="Trunk",
        postprocess=lambda x: not x,
        on_icon="mdi:car-back",
        off_icon="mdi:car-back",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    FiatBinarySensorEntityDescription(
        key="window_driver_closed",
        name="Window Driver",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door",
        off_icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    FiatBinarySensorEntityDescription(
        key="window_passenger_closed",
        name="Window Passenger",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door",
        off_icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    FiatBinarySensorEntityDescription(
        key="plugged_in",
        name="EV Charger",
        device_class=BinarySensorDeviceClass.PLUG,
    ),
    FiatBinarySensorEntityDescription(
        key="charging",
        name="Charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    ),
    FiatBinarySensorEntityDescription(
        key="wheel_front_left_pressure_warning",
        name="Tire Pressure Front Left Warning",
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    FiatBinarySensorEntityDescription(
        key="wheel_front_right_pressure_warning",
        name="Tire Pressure Front Right Warning",
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    FiatBinarySensorEntityDescription(
        key="wheel_rear_right_pressure_warning",
        name="Tire Pressure Rear Right Warning",
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    FiatBinarySensorEntityDescription(
        key="wheel_rear_left_pressure_warning",
        name="Tire Pressure Rear Left Warning",
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
            if getattr(vehicle, description.key) is not None:
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
        self.key = description.key
        self.postprocess = description.postprocess
        self.entity_description: FiatBinarySensorEntityDescription = description
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_{description.key}"
        self._attr_name = f"{vehicle.make} {
            vehicle.nickname or vehicle.model} {description.name}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""

        if self.entity_description.is_on is not None:
            v = self.entity_description.is_on(self.vehicle)
        else:
            v = getattr(self.vehicle, self.key)

        if self.postprocess is not None:
            v = self.postprocess(v)

        return v

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
