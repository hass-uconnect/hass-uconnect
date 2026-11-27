"""Sensor for Uconnect integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    Platform,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from py_uconnect import Vehicle

from .const import DOMAIN, UNIT_DYNAMIC
from .coordinator import UconnectConfigEntry, UconnectDataUpdateCoordinator
from .entity import UconnectEntity, should_add
from .extrapolated_soc import (
    UconnectChargingRateSensor,
    UconnectExtrapolatedSocSensor,
)
from .ssdp import sensor as ssdp_sensor
from .ssdp.coordinator import SsdpDataUpdateCoordinator

# Units reported by the API that differ from the Home Assistant ones
UNIT_ALIASES: Final[dict[str, str]] = {
    "C": UnitOfTemperature.CELSIUS,
    "F": UnitOfTemperature.FAHRENHEIT,
}


def _timestamp(ms: Any) -> datetime | None:
    """Convert a millisecond Unix timestamp to a datetime."""

    if not isinstance(ms, int | float) or isinstance(ms, bool):
        return None

    return dt_util.utc_from_timestamp(ms / 1000)


@dataclass(frozen=True, kw_only=True)
class UconnectSensorEntityDescription(SensorEntityDescription):
    """A class that describes custom sensor entities."""

    get: Callable[[Vehicle], Any] | None = None


SENSOR_DESCRIPTIONS: Final[tuple[UconnectSensorEntityDescription, ...]] = (
    UconnectSensorEntityDescription(
        key="odometer",
        translation_key="odometer",
        icon="mdi:counter",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UNIT_DYNAMIC,
        suggested_display_precision=2,
    ),
    UconnectSensorEntityDescription(
        key="distance_to_empty",
        translation_key="distance_to_empty",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UNIT_DYNAMIC,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="range_gas",
        translation_key="range_gas",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UNIT_DYNAMIC,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="range_total",
        translation_key="range_total",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UNIT_DYNAMIC,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="state_of_charge",
        translation_key="state_of_charge",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.BATTERY,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="charging_level",
        translation_key="charging_level",
        icon="mdi:ev-station",
    ),
    UconnectSensorEntityDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        icon="mdi:car-battery",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=1,
    ),
    UconnectSensorEntityDescription(
        key="time_to_fully_charge_l2",
        translation_key="time_to_fully_charge_l2",
        icon="mdi:battery-clock",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.DURATION,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="time_to_fully_charge_l3",
        translation_key="time_to_fully_charge_l3",
        icon="mdi:battery-clock",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.DURATION,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="distance_to_service",
        translation_key="distance_to_service",
        icon="mdi:car-wrench",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UNIT_DYNAMIC,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="days_to_service",
        translation_key="days_to_service",
        icon="mdi:car-wrench",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfTime.DAYS,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="wheel_front_left_pressure",
        translation_key="wheel_front_left_pressure",
        icon="mdi:tire",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UNIT_DYNAMIC,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="wheel_front_right_pressure",
        translation_key="wheel_front_right_pressure",
        icon="mdi:tire",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UNIT_DYNAMIC,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="wheel_rear_left_pressure",
        translation_key="wheel_rear_left_pressure",
        icon="mdi:tire",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UNIT_DYNAMIC,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="wheel_rear_right_pressure",
        translation_key="wheel_rear_right_pressure",
        icon="mdi:tire",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UNIT_DYNAMIC,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="oil_level",
        translation_key="oil_level",
        icon="mdi:oil",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="fuel_amount",
        translation_key="fuel_amount",
        icon="mdi:fuel",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="timestamp_info",
        translation_key="timestamp_info",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    UconnectSensorEntityDescription(
        key="timestamp_status",
        translation_key="timestamp_status",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    UconnectSensorEntityDescription(
        key="last_location_update",
        translation_key="last_location_update",
        icon="mdi:update",
        get=lambda x: x.location.updated if x.location else None,
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    UconnectSensorEntityDescription(
        key="fuel_type",
        translation_key="fuel_type",
        icon="mdi:gas-station",
    ),
    UconnectSensorEntityDescription(
        key="battery_state_of_charge",
        translation_key="battery_state_of_charge",
        icon="mdi:battery",
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="time_to_fully_charge_l1",
        translation_key="time_to_fully_charge_l1",
        icon="mdi:battery-clock",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.DURATION,
        suggested_display_precision=0,
    ),
    UconnectSensorEntityDescription(
        key="hvac_temperature",
        translation_key="hvac_temperature",
        icon="mdi:thermometer",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UNIT_DYNAMIC,
        suggested_display_precision=1,
    ),
    UconnectSensorEntityDescription(
        key="privacy_mode",
        translation_key="privacy_mode",
        icon="mdi:incognito",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UconnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform."""
    if isinstance(config_entry.runtime_data, SsdpDataUpdateCoordinator):
        await ssdp_sensor.async_setup_entry(hass, config_entry, async_add_entities)
        return

    coordinator = config_entry.runtime_data
    entities: list[SensorEntity] = []

    def add(vin: str, key: str, supported: bool) -> bool:
        return should_add(hass, Platform.SENSOR, f"{DOMAIN}_{vin}_{key}", supported)

    for vehicle in coordinator.client.vehicles.values():
        vin = vehicle.vin

        for description in SENSOR_DESCRIPTIONS:
            if add(
                vin,
                description.key,
                description.get is not None
                or getattr(vehicle, description.key, None) is not None,
            ):
                entities.append(UconnectSensor(coordinator, description, vehicle))

        if add(vin, "vhr", vin in coordinator.vhr_data):
            entities.append(UconnectVhrSensor(coordinator, vehicle))

        if add(vin, "maintenance", vin in coordinator.maintenance_data):
            entities.append(UconnectMaintenanceSensor(coordinator, vehicle))

        if add(vin, "charge_schedule", vehicle.charge_schedules is not None):
            entities.append(UconnectChargeScheduleSensor(coordinator, vehicle))

        # Extrapolated SOC sensors for EVs/PHEVs
        if add(vin, "extrapolated_soc", vehicle.state_of_charge is not None):
            sensor = UconnectExtrapolatedSocSensor(coordinator, vehicle)
            entities.append(sensor)
            coordinator.extrapolated_soc_sensors[vin] = sensor
            entities.append(UconnectChargingRateSensor(coordinator, vehicle))

    async_add_entities(entities)


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
        self._attr_translation_key = self._description.translation_key
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_{self._key}"
        self._attr_icon = self._description.icon
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
            unit = getattr(self.vehicle, f"{self._key}_unit", None)
            return UNIT_ALIASES.get(unit, unit) if unit is not None else None

        return self._description.native_unit_of_measurement


class UconnectVhrSensor(SensorEntity, UconnectEntity):
    """Uconnect Vehicle Health Report sensor."""

    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
    ):
        """Initialize the VHR sensor."""

        super().__init__(coordinator, vehicle)

        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_vhr"
        self._attr_icon = "mdi:car-wrench"
        self._attr_translation_key = "vhr"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return the report timestamp."""

        data = self.coordinator.vhr_data.get(self._vin)
        if data is None:
            return None

        report_card = data.get("reportCard")
        if not isinstance(report_card, dict):
            return None

        return _timestamp(report_card.get("timestamp"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the report items as attributes."""

        data = self.coordinator.vhr_data.get(self._vin)
        if data is None:
            return None

        report_card = data.get("reportCard")
        if not isinstance(report_card, dict):
            return None

        attrs: dict[str, Any] = {}

        for category in report_card.get("items", []):
            cat_key = category.get("itemKey", "unknown")
            attrs[cat_key] = category.get("value")

            for item in category.get("items", []):
                item_key = item.get("itemKey", "unknown")
                attrs[f"{cat_key}.{item_key}"] = item.get("value")

        return attrs


class UconnectMaintenanceSensor(SensorEntity, UconnectEntity):
    """Uconnect Maintenance History sensor."""

    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
    ):
        """Initialize the maintenance sensor."""

        super().__init__(coordinator, vehicle)

        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_maintenance"
        self._attr_icon = "mdi:wrench-clock"
        self._attr_translation_key = "maintenance"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    def _get_history(self) -> list[dict]:
        """Return the service history list."""

        data = self.coordinator.maintenance_data.get(self._vin)
        if data is None:
            return []

        history = data.get("serviceHistory")
        if not isinstance(history, list):
            return []

        return history

    @property
    def native_value(self) -> datetime | None:
        """Return the most recent service date."""

        history = self._get_history()
        if not history:
            return None

        return _timestamp(history[0].get("date"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return details of the most recent service record."""

        history = self._get_history()
        if not history:
            return None

        latest = history[0]

        return {
            "last_service_description": latest.get("description"),
            "last_service_dealer": latest.get("dealer"),
            "last_service_odometer": latest.get("odometer"),
            "last_service_location": latest.get("location"),
            "total_records": len(history),
        }


class UconnectChargeScheduleSensor(SensorEntity, UconnectEntity):
    """Uconnect Charge Schedule sensor."""

    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
    ):
        """Initialize the charge schedule sensor."""

        super().__init__(coordinator, vehicle)

        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_charge_schedule"
        self._attr_icon = "mdi:calendar-clock"
        self._attr_translation_key = "charge_schedule"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the number of schedules."""

        schedules = self.vehicle.charge_schedules
        return len(schedules) if schedules is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the schedules, in the format set_charge_schedule accepts."""

        schedules = self.vehicle.charge_schedules
        if schedules is None:
            return None

        return {"schedules": schedules}
