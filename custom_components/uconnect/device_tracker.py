"""Device Tracker for Uconnect integration."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from py_uconnect import Vehicle

from .const import DOMAIN
from .coordinator import UconnectConfigEntry, UconnectDataUpdateCoordinator
from .entity import UconnectEntity, should_add, vehicle_name


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UconnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    entities = []
    for vehicle in coordinator.client.vehicles.values():
        if should_add(
            hass,
            Platform.DEVICE_TRACKER,
            f"{DOMAIN}_{vehicle.vin}_location",
            vehicle.location is not None,
        ):
            entities.append(UconnectTracker(coordinator, vehicle))

    async_add_entities(entities)


class UconnectTracker(TrackerEntity, UconnectEntity):
    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
    ):
        UconnectEntity.__init__(self, coordinator, vehicle)
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_location"
        self._attr_name = f"{vehicle_name(vehicle)} Location"
        self._attr_icon = "mdi:map-marker-outline"

    @property
    def latitude(self):
        if self.vehicle.location is None:
            return None
        return self.vehicle.location.latitude

    @property
    def longitude(self):
        if self.vehicle.location is None:
            return None
        return self.vehicle.location.longitude

    @property
    def source_type(self):
        return SourceType.GPS
