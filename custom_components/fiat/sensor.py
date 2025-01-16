"""Sensor for Fiat integration."""

from __future__ import annotations

import logging
from typing import Final
from datetime import date

from pyfiat.client import Vehicle

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import FiatEntity
from .coordinator import FiatDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTIONS: Final[tuple[SensorEntityDescription, ...]] = (
    SensorEntityDescription(
        key="odometer",
        name="Odometer",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
    ),
    SensorEntityDescription(
        key="distance_to_empty",
        name="Driving Range Left",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
    ),
    SensorEntityDescription(
        key="state_of_charge",
        name="HVBattery Charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
    ),
    SensorEntityDescription(
        key="battery_voltage",
        name="12V Battery Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
    ),
    SensorEntityDescription(
        key="distance_to_service",
        name="Distance to service",
        icon="mdi:car-wrench",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
    ),
    SensorEntityDescription(
        key="days_to_service",
        name="Days to service",
        icon="mdi:car-wrench",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform."""

    coordinator: FiatDataUpdateCoordinator = hass.data[DOMAIN][config_entry.unique_id]
    entities = []

    for vehicle in coordinator.client.get_vehicles().values():
        for description in SENSOR_DESCRIPTIONS:
            if getattr(vehicle, description.key, None) is not None:
                entities.append(
                    FiatSensor(coordinator, description, vehicle)
                )

    async_add_entities(entities)
    return True


class FiatSensor(SensorEntity, FiatEntity):
    """Fiat sensor class."""

    def __init__(
        self, coordinator, description: SensorEntityDescription, vehicle: Vehicle
    ):
        """Initialize the sensor."""

        super().__init__(coordinator, vehicle)

        self._description = description
        self._key = self._description.key
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_{self._key}"
        self._attr_icon = self._description.icon
        self._attr_name = f"{vehicle.make} {
            vehicle.nickname or vehicle.model} {description.name}"
        self._attr_state_class = self._description.state_class
        self._attr_device_class = self._description.device_class

    @property
    def native_value(self):
        """Return the value reported by the sensor."""
        return getattr(self.vehicle, self._key)

    @property
    def native_unit_of_measurement(self):
        """Return the unit the value was reported in by the sensor"""

        return self._description.native_unit_of_measurement
