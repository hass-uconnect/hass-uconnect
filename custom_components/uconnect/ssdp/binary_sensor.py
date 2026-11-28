"""Binary sensors of the SSDP vehicles"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from stellantis_ssdp import Vehicle

from ..const import DOMAIN
from ..coordinator import UconnectConfigEntry
from ..entity import should_add
from .coordinator import SsdpDataUpdateCoordinator
from .entity import SsdpEntity


@dataclass(frozen=True, kw_only=True)
class SsdpBinarySensorEntityDescription(BinarySensorEntityDescription):
    """A binary sensor of an SSDP vehicle"""

    value: Callable[[Vehicle], bool | None]


def _unlocked(v: Vehicle) -> bool | None:
    return None if v.locked is None else not v.locked


def _opening(identifier: str) -> Callable[[Vehicle], bool | None]:
    return lambda v: v.openings.get(identifier)


def _tyre_warning(position: str) -> Callable[[Vehicle], bool | None]:
    def value(v: Vehicle) -> bool | None:
        status = v.tyres.get(position)
        return None if status is None else status != "Normal"

    return value


BINARY_SENSORS: tuple[SsdpBinarySensorEntityDescription, ...] = (
    SsdpBinarySensorEntityDescription(
        key="ignition_on",
        device_class=BinarySensorDeviceClass.POWER,
        value=lambda v: v.ignition_on,
    ),
    SsdpBinarySensorEntityDescription(
        key="plugged_in",
        device_class=BinarySensorDeviceClass.PLUG,
        value=lambda v: v.plugged_in,
    ),
    SsdpBinarySensorEntityDescription(
        key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value=lambda v: v.charging,
    ),
    SsdpBinarySensorEntityDescription(
        key="hvac_on",
        device_class=BinarySensorDeviceClass.RUNNING,
        value=lambda v: v.preconditioning_on,
    ),
    SsdpBinarySensorEntityDescription(
        key="doors_locked",
        # On means unlocked
        device_class=BinarySensorDeviceClass.LOCK,
        value=_unlocked,
    ),
    SsdpBinarySensorEntityDescription(
        key="moving",
        device_class=BinarySensorDeviceClass.MOVING,
        value=lambda v: v.moving,
    ),
    *(
        SsdpBinarySensorEntityDescription(
            key=key, device_class=device_class, value=_opening(identifier)
        )
        for key, identifier, device_class in (
            ("door_driver_open", "Driver", BinarySensorDeviceClass.DOOR),
            ("door_passenger_open", "Passenger", BinarySensorDeviceClass.DOOR),
            ("door_rear_left_open", "RearLeft", BinarySensorDeviceClass.DOOR),
            ("door_rear_right_open", "RearRight", BinarySensorDeviceClass.DOOR),
            ("trunk_open", "Trunk", BinarySensorDeviceClass.OPENING),
            ("hood_open", "HoodDoor", BinarySensorDeviceClass.OPENING),
            ("rear_window_open", "RearWindow", BinarySensorDeviceClass.WINDOW),
            ("roof_window_open", "RoofWindow", BinarySensorDeviceClass.WINDOW),
        )
    ),
    *(
        SsdpBinarySensorEntityDescription(
            key=f"wheel_{key}_pressure_warning",
            device_class=BinarySensorDeviceClass.PROBLEM,
            icon="mdi:car-tire-alert",
            value=_tyre_warning(position),
        )
        for key, position in (
            ("front_left", "FrontLeft"),
            ("front_right", "FrontRight"),
            ("rear_left", "RearLeft"),
            ("rear_right", "RearRight"),
        )
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UconnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SsdpDataUpdateCoordinator = config_entry.runtime_data  # type: ignore[assignment]

    async_add_entities(
        SsdpBinarySensor(coordinator, vehicle, description)
        for vehicle in coordinator.vehicles.values()
        for description in BINARY_SENSORS
        if should_add(
            hass,
            Platform.BINARY_SENSOR,
            f"{DOMAIN}_{vehicle.vin}_{description.key}",
            description.value(vehicle) is not None,
        )
    )


class SsdpBinarySensor(SsdpEntity, BinarySensorEntity):
    entity_description: SsdpBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: SsdpDataUpdateCoordinator,
        vehicle: Vehicle,
        description: SsdpBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, vehicle, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self.vehicle)
