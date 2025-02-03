"""Sensor for Uconnect integration."""

from __future__ import annotations

import logging
from typing import Final

from py_uconnect.client import Vehicle

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfTime,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, UNIT_DYNAMIC
from .entity import UconnectEntity
from .coordinator import UconnectDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTIONS: Final[tuple[SensorEntityDescription, ...]] = (
    SensorEntityDescription(
        key="odometer",
        name="Odometer",
        icon="mdi:counter",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    SensorEntityDescription(
        key="distance_to_empty",
        name="Driving Range",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    SensorEntityDescription(
        key="state_of_charge",
        name="HVBattery Charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
    ),
    SensorEntityDescription(
        key="charging_level",
        name="Charger Type",
        icon="mdi:ev-station",
    ),
    SensorEntityDescription(
        key="charging_level_preference",
        name="Charging Level Pref",
        icon="mdi:cog-stop",
    ),
    SensorEntityDescription(
        key="battery_voltage",
        name="12V Battery",
        icon="mdi:car-battery",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
    ),
    SensorEntityDescription(
        key="time_to_fully_charge_l2",
        name="Time to Charge L2",
        icon="mdi:battery-clock",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
    ),
    SensorEntityDescription(
        key="time_to_fully_charge_l3",
        name="Time to Charge L3",
        icon="mdi:battery-clock",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
    ),
    SensorEntityDescription(
        key="distance_to_service",
        name="Distance to Service",
        icon="mdi:car-wrench",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    SensorEntityDescription(
        key="days_to_service",
        name="Days till service needed",
        icon="mdi:car-wrench",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
    ),
    SensorEntityDescription(
        key="wheel_front_left_pressure",
        name="Front Left Tire Pressure",
        icon="mdi:tire",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    SensorEntityDescription(
        key="wheel_front_right_pressure",
        name="Front Right Tire Pressure",
        icon="mdi:tire",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    SensorEntityDescription(
        key="wheel_rear_left_pressure",
        name="Rear Left Tire Pressure",
        icon="mdi:tire",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    SensorEntityDescription(
        key="wheel_rear_right_pressure",
        name="Rear Right Tire Pressure",
        icon="mdi:tire",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    SensorEntityDescription(
        key="oil_level",
        name="Oil Level",
        icon="mdi:oil",
        native_unit_of_measurement=PERCENTAGE,
    ),
    SensorEntityDescription(
        key="fuel_amount",
        name="Fuel Remaining",
        icon="mdi:fuel",
        native_unit_of_measurement=PERCENTAGE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform."""

    coordinator: UconnectDataUpdateCoordinator = hass.data[DOMAIN][config_entry.unique_id]
    entities = []

    for vehicle in coordinator.client.get_vehicles().values():
        for description in SENSOR_DESCRIPTIONS:
            if getattr(vehicle, description.key, None) is not None:
                entities.append(
                    UconnectSensor(coordinator, description, vehicle)
                )

    async_add_entities(entities)
    return True


class UconnectSensor(SensorEntity, UconnectEntity):
    """Uconnect sensor class."""

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

        if self._description.native_unit_of_measurement == UNIT_DYNAMIC:
            return getattr(self.vehicle, f"{self._key}_unit")

        return self._description.native_unit_of_measurement
