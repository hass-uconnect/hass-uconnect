"""Sensor for Uconnect integration."""

from __future__ import annotations
from typing import Final, Callable, Any

from dataclasses import dataclass

from py_uconnect.client import Vehicle

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
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
from .extrapolated_soc import (
    UconnectExtrapolatedSocSensor,
    UconnectChargingRateSensor,
)


@dataclass
class UconnectSensorEntityDescription(SensorEntityDescription):
    """A class that describes custom sensor entities."""

    get: Callable[[Vehicle], Any] | None = None


SENSOR_DESCRIPTIONS: Final[tuple[UconnectSensorEntityDescription, ...]] = (
    UconnectSensorEntityDescription(
        key="odometer",
        name="Odometer",
        icon="mdi:counter",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    UconnectSensorEntityDescription(
        key="distance_to_empty",
        name="Driving Range",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    UconnectSensorEntityDescription(
        key="range_gas",
        name="Driving Range (Gas)",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    UconnectSensorEntityDescription(
        key="range_total",
        name="Driving Range (Total)",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    UconnectSensorEntityDescription(
        key="state_of_charge",
        name="HVBattery Charge",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.BATTERY,
    ),
    UconnectSensorEntityDescription(
        key="charging_level",
        name="Charger Type",
        icon="mdi:ev-station",
    ),
    UconnectSensorEntityDescription(
        key="battery_voltage",
        name="12V Battery",
        icon="mdi:car-battery",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLTAGE,
    ),
    UconnectSensorEntityDescription(
        key="time_to_fully_charge_l2",
        name="Time to Charge L2",
        icon="mdi:battery-clock",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.DURATION,
    ),
    UconnectSensorEntityDescription(
        key="time_to_fully_charge_l3",
        name="Time to Charge L3",
        icon="mdi:battery-clock",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.DURATION,
    ),
    UconnectSensorEntityDescription(
        key="distance_to_service",
        name="Distance to Service",
        icon="mdi:car-wrench",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    UconnectSensorEntityDescription(
        key="days_to_service",
        name="Days till service needed",
        icon="mdi:car-wrench",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfTime.DAYS,
    ),
    UconnectSensorEntityDescription(
        key="wheel_front_left_pressure",
        name="Front Left Tire Pressure",
        icon="mdi:tire",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    UconnectSensorEntityDescription(
        key="wheel_front_right_pressure",
        name="Front Right Tire Pressure",
        icon="mdi:tire",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    UconnectSensorEntityDescription(
        key="wheel_rear_left_pressure",
        name="Rear Left Tire Pressure",
        icon="mdi:tire",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    UconnectSensorEntityDescription(
        key="wheel_rear_right_pressure",
        name="Rear Right Tire Pressure",
        icon="mdi:tire",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UNIT_DYNAMIC,
    ),
    UconnectSensorEntityDescription(
        key="oil_level",
        name="Oil Level",
        icon="mdi:oil",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    UconnectSensorEntityDescription(
        key="fuel_amount",
        name="Fuel Remaining",
        icon="mdi:fuel",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    UconnectSensorEntityDescription(
        key="timestamp_info",
        name="Last Info Update At",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    UconnectSensorEntityDescription(
        key="timestamp_status",
        name="Last Status Update At",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    UconnectSensorEntityDescription(
        key="last_location_update",
        name="Last Location Update At",
        icon="mdi:update",
        get=lambda x: x.location.updated,
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform."""

    coordinator: UconnectDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.unique_id
    ]
    entities = []

    for vehicle in coordinator.client.get_vehicles().values():
        for description in SENSOR_DESCRIPTIONS:
            if (
                getattr(vehicle, description.key, None) is not None
                or description.get is not None
            ):
                entities.append(UconnectSensor(
                    coordinator, description, vehicle))

        # Add extrapolated SOC sensors for EVs/PHEVs
        if getattr(vehicle, "state_of_charge", None) is not None:
            entities.append(UconnectExtrapolatedSocSensor(coordinator, vehicle))
            entities.append(UconnectChargingRateSensor(coordinator, vehicle))

    async_add_entities(entities)
    return True


class UconnectSensor(SensorEntity, UconnectEntity):
    """Uconnect sensor class."""

    def __init__(
        self,
        coordinator,
        description: UconnectSensorEntityDescription,
        vehicle: Vehicle,
    ):
        """Initialize the sensor."""

        super().__init__(coordinator, vehicle)

        self._description: UconnectSensorEntityDescription = description
        self._key = self._description.key
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_{self._key}"
        self._attr_icon = self._description.icon
        self._attr_name = f"{vehicle.make} {
            vehicle.nickname or vehicle.model} {description.name}"
        self._attr_state_class = self._description.state_class
        self._attr_device_class = self._description.device_class

    @property
    def native_value(self):
        """Return the value reported by the sensor"""

        if self._description.get is not None:
            return self._description.get(self.vehicle)

        return getattr(self.vehicle, self._key)

    @property
    def native_unit_of_measurement(self):
        """Return the unit the value was reported in by the sensor"""

        if self._description.native_unit_of_measurement == UNIT_DYNAMIC:
            return getattr(self.vehicle, f"{self._key}_unit")

        return self._description.native_unit_of_measurement
