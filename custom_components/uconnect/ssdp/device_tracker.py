"""Location of the SSDP vehicles"""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DOMAIN
from ..coordinator import UconnectConfigEntry
from ..entity import should_add
from .coordinator import SsdpDataUpdateCoordinator
from .entity import SsdpEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UconnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SsdpDataUpdateCoordinator = config_entry.runtime_data  # type: ignore[assignment]

    async_add_entities(
        SsdpTracker(coordinator, vehicle, "location")
        for vehicle in coordinator.vehicles.values()
        if should_add(
            hass,
            Platform.DEVICE_TRACKER,
            f"{DOMAIN}_{vehicle.vin}_location",
            vehicle.location is not None,
        )
    )


class SsdpTracker(SsdpEntity, TrackerEntity):
    _attr_source_type = SourceType.GPS
    _attr_icon = "mdi:map-marker-outline"

    @property
    def latitude(self) -> float | None:
        location = self.vehicle.location
        return location.latitude if location else None

    @property
    def longitude(self) -> float | None:
        location = self.vehicle.location
        return location.longitude if location else None
