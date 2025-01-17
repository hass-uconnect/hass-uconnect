"""Device Tracker for Fiat integration."""

from __future__ import annotations

import logging

from pyfiat.client import Vehicle

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FiatDataUpdateCoordinator
from .entity import FiatEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FiatDataUpdateCoordinator = hass.data[DOMAIN][config_entry.unique_id]
    entities = []
    for vehicle in coordinator.client.vehicles.values():
        if vehicle.location is not None:
            entities.append(FiatTracker(coordinator, vehicle))

    async_add_entities(entities)
    return True


class FiatTracker(TrackerEntity, FiatEntity):
    def __init__(
        self,
        coordinator: FiatDataUpdateCoordinator,
        vehicle: Vehicle,
    ):
        FiatEntity.__init__(self, coordinator, vehicle)
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_location"
        self._attr_name = f"{vehicle.make} {
            vehicle.nickname or vehicle.model} Location"
        self._attr_icon = "mdi:map-marker-outline"

    @property
    def latitude(self):
        return self.vehicle.location.latitude

    @property
    def longitude(self):
        return self.vehicle.location.longitude

    @property
    def battery_level(self):
        return self.vehicle.state_of_charge

    @property
    def source_type(self):
        return SourceType.GPS
