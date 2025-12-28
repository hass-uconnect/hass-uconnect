"""Sensor for Uconnect integration."""

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

from py_uconnect.client import Vehicle

from .const import DOMAIN
from .coordinator import UconnectDataUpdateCoordinator
from .entity import UconnectEntity


@dataclass
class UconnectBinarySensorEntityDescription(BinarySensorEntityDescription):
    """A class that describes custom binary sensor entities."""

    is_on: Callable[[Vehicle], bool] | None = None
    postprocess: Callable[[bool], bool] | None = None
    on_icon: str | None = None
    off_icon: str | None = None


SENSOR_DESCRIPTIONS: Final[tuple[UconnectBinarySensorEntityDescription, ...]] = (
    UconnectBinarySensorEntityDescription(
        key="ignition_on",
        name="Ignition",
        on_icon="mdi:engine",
        off_icon="mdi:engine-off",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    UconnectBinarySensorEntityDescription(
        key="ev_running",
        name="EV Running",
        on_icon="mdi:engine",
        off_icon="mdi:engine-off",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    UconnectBinarySensorEntityDescription(
        key="door_driver_locked",
        name="Door Driver",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door-lock",
        off_icon="mdi:car-door-lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    UconnectBinarySensorEntityDescription(
        key="door_passenger_locked",
        name="Door Passenger",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door-lock",
        off_icon="mdi:car-door-lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    UconnectBinarySensorEntityDescription(
        key="door_rear_left_locked",
        name="Door Rear Left",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door-lock",
        off_icon="mdi:car-door-lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    UconnectBinarySensorEntityDescription(
        key="door_rear_right_locked",
        name="Door Rear Right",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door-lock",
        off_icon="mdi:car-door-lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    UconnectBinarySensorEntityDescription(
        key="trunk_locked",
        name="Trunk",
        postprocess=lambda x: not x,
        on_icon="mdi:car-back",
        off_icon="mdi:car-back",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    UconnectBinarySensorEntityDescription(
        key="window_driver_closed",
        name="Window Driver",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door",
        off_icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    UconnectBinarySensorEntityDescription(
        key="window_passenger_closed",
        name="Window Passenger",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door",
        off_icon="mdi:car-door",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    UconnectBinarySensorEntityDescription(
        key="plugged_in",
        name="EV Charger",
        on_icon="mdi:power-plug",
        off_icon="mdi:power-plug-off",
        device_class=BinarySensorDeviceClass.PLUG,
    ),
    UconnectBinarySensorEntityDescription(
        key="charging",
        name="Charging",
        on_icon="mdi:battery-charging",
        off_icon="mdi:battery-alert",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    ),
    UconnectBinarySensorEntityDescription(
        key="wheel_front_left_pressure_warning",
        name="Tire Pressure Front Left Warning",
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    UconnectBinarySensorEntityDescription(
        key="wheel_front_right_pressure_warning",
        name="Tire Pressure Front Right Warning",
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    UconnectBinarySensorEntityDescription(
        key="wheel_rear_right_pressure_warning",
        name="Tire Pressure Rear Right Warning",
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    UconnectBinarySensorEntityDescription(
        key="wheel_rear_left_pressure_warning",
        name="Tire Pressure Rear Left Warning",
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    UconnectBinarySensorEntityDescription(
        key="fuel_low",
        name="Low Fuel",
        on_icon="mdi:gas-station",
        off_icon="mdi:fuel",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary_sensor platform."""

    coordinator: UconnectDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.unique_id
    ]
    entities: list[UconnectBinarySensor] = []

    for vehicle in coordinator.client.vehicles.values():
        for description in SENSOR_DESCRIPTIONS:
            if getattr(vehicle, description.key) is not None:
                entities.append(UconnectBinarySensor(coordinator, description, vehicle))

    async_add_entities(entities)
    return True


class UconnectBinarySensor(BinarySensorEntity, UconnectEntity):
    """Uconnect binary sensor class."""

    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        description: UconnectBinarySensorEntityDescription,
        vehicle: Vehicle,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle)
        self.key = description.key
        self.postprocess = description.postprocess
        self.entity_description: UconnectBinarySensorEntityDescription = description
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

        if v is not None and self.postprocess is not None:
            v = self.postprocess(v)

        return v

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""

        if self.entity_description.on_icon is None:
            return None

        return (
            self.entity_description.on_icon
            if self.is_on
            else self.entity_description.off_icon or self.entity_description.on_icon
        )
