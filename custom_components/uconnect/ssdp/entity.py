"""Base entity of the SSDP vehicles"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from stellantis_ssdp import Vehicle

from ..const import DOMAIN
from ..coordinator import UconnectConfigEntry
from .coordinator import SsdpDataUpdateCoordinator

# Model names of the family codes in the vehicle list
FAMILY_NAMES = {
    "J4U": "Compass",
}


def vehicle_model(vehicle: Vehicle) -> str | None:
    """Return the model name of a vehicle, the family code if unknown"""

    if vehicle.family is None:
        return None

    return FAMILY_NAMES.get(vehicle.family.upper(), vehicle.family)


def vehicle_name(vehicle: Vehicle) -> str:
    """Return the name of the vehicle, the device name"""

    parts = [vehicle.brand, vehicle_model(vehicle)]
    return " ".join(p for p in parts if p) or vehicle.vin


def command_entities_enabled(
    config_entry: UconnectConfigEntry, coordinator: SsdpDataUpdateCoordinator
) -> bool:
    """Whether to create the entities that send remote commands: they are
    enabled in the options and remote commands are set up"""

    return coordinator.command_entities


class SsdpEntity(CoordinatorEntity[SsdpDataUpdateCoordinator]):
    """An entity of an SSDP vehicle"""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SsdpDataUpdateCoordinator, vehicle: Vehicle, key: str
    ) -> None:
        super().__init__(coordinator)
        self._vin = vehicle.vin
        self._last_vehicle = vehicle
        self._key = key
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_{key}"
        self._attr_translation_key = key

    @property
    def vehicle(self) -> Vehicle:
        """The current vehicle object, the last known one if it was removed
        from the account (the entity is then unavailable)"""

        vehicle = self.coordinator.vehicles.get(self._vin)
        if vehicle is not None:
            self._last_vehicle = vehicle
        return self._last_vehicle

    @property
    def available(self) -> bool:
        return super().available and self._vin in self.coordinator.vehicles

    @property
    def device_info(self) -> DeviceInfo:
        vehicle = self.vehicle
        return DeviceInfo(
            identifiers={(DOMAIN, vehicle.vin)},
            manufacturer=vehicle.brand,
            model=vehicle_model(vehicle),
            name=vehicle_name(vehicle),
            serial_number=vehicle.vin,
        )
