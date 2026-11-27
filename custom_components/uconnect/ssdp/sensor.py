"""Sensors of the SSDP vehicles"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from stellantis_ssdp import Vehicle

from ..const import DOMAIN
from ..coordinator import UconnectConfigEntry
from ..entity import should_add
from .coordinator import SsdpDataUpdateCoordinator
from .entity import SsdpEntity


def _has_battery(v: Vehicle) -> bool:
    return v.state_of_charge is not None


def _privacy(v: Vehicle) -> str | None:
    """The privacy state as reported, "None" when privacy mode is off"""

    privacy = (v.raw_telemetry or {}).get("privacy")
    state = privacy.get("state") if isinstance(privacy, dict) else None
    return state if isinstance(state, str) else None


def _range_total(v: Vehicle) -> int | None:
    if v.range_electric is None or v.range_fuel is None:
        return None
    return v.range_electric + v.range_fuel


@dataclass(frozen=True, kw_only=True)
class SsdpSensorEntityDescription(SensorEntityDescription):
    """A sensor of an SSDP vehicle"""

    value: Callable[[Vehicle], Any]


# The keys of values that mean the same as for Uconnect vehicles are the same
# (translations, vehicle card)
SENSORS: tuple[SsdpSensorEntityDescription, ...] = (
    SsdpSensorEntityDescription(
        key="state_of_charge",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.BATTERY,
        suggested_display_precision=0,
        value=lambda v: v.state_of_charge,
    ),
    SsdpSensorEntityDescription(
        key="distance_to_empty",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        # The electric range of vehicles with a battery, like for Uconnect
        value=lambda v: v.range_electric if _has_battery(v) else v.range_fuel,
    ),
    SsdpSensorEntityDescription(
        key="range_gas",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        value=lambda v: v.range_fuel if _has_battery(v) else None,
    ),
    SsdpSensorEntityDescription(
        key="range_total",
        icon="mdi:road-variant",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        value=_range_total,
    ),
    SsdpSensorEntityDescription(
        key="fuel_amount",
        icon="mdi:fuel",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value=lambda v: v.fuel_level,
    ),
    SsdpSensorEntityDescription(
        key="odometer",
        icon="mdi:counter",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=1,
        value=lambda v: v.odometer,
    ),
    SsdpSensorEntityDescription(
        key="days_to_service",
        icon="mdi:car-wrench",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfTime.DAYS,
        suggested_display_precision=0,
        value=lambda v: v.days_to_service,
    ),
    SsdpSensorEntityDescription(
        key="distance_to_service",
        icon="mdi:car-wrench",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        value=lambda v: v.distance_to_service,
    ),
    SsdpSensorEntityDescription(
        key="battery_voltage",
        icon="mdi:car-battery",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=1,
        # The API's 12V "residual" is the voltage, its "voltage" a level
        value=lambda v: v.aux_battery_residual,
    ),
    SsdpSensorEntityDescription(
        key="battery_12v_level",
        icon="mdi:car-battery",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value=lambda v: v.aux_battery_voltage,
    ),
    SsdpSensorEntityDescription(
        key="battery_health",
        icon="mdi:battery-heart-variant",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value=lambda v: v.battery_health,
    ),
    SsdpSensorEntityDescription(
        key="battery_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value=lambda v: v.battery_temperature,
    ),
    SsdpSensorEntityDescription(
        key="charging_status",
        icon="mdi:ev-station",
        value=lambda v: v.charging_status,
    ),
    SsdpSensorEntityDescription(
        key="fuel_type",
        icon="mdi:gas-station",
        value=lambda v: v.fuel_type,
    ),
    SsdpSensorEntityDescription(
        key="privacy_mode",
        icon="mdi:incognito",
        value=_privacy,
    ),
    SsdpSensorEntityDescription(
        key="timestamp_status",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda v: v.timestamp,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UconnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SsdpDataUpdateCoordinator = config_entry.runtime_data  # type: ignore[assignment]

    async_add_entities(
        SsdpSensor(coordinator, vehicle, description)
        for vehicle in coordinator.vehicles.values()
        for description in SENSORS
        if should_add(
            hass,
            Platform.SENSOR,
            f"{DOMAIN}_{vehicle.vin}_{description.key}",
            description.value(vehicle) is not None,
        )
    )


class SsdpSensor(SsdpEntity, SensorEntity):
    entity_description: SsdpSensorEntityDescription

    def __init__(
        self,
        coordinator: SsdpDataUpdateCoordinator,
        vehicle: Vehicle,
        description: SsdpSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, vehicle, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.vehicle)
