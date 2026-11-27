"""Door lock of the SSDP vehicles"""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from stellantis_ssdp import remote

from ..const import DOMAIN
from ..coordinator import UconnectConfigEntry
from ..entity import should_add
from .coordinator import SsdpDataUpdateCoordinator
from .entity import SsdpEntity, command_entities_enabled


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UconnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SsdpDataUpdateCoordinator = config_entry.runtime_data  # type: ignore[assignment]
    if not command_entities_enabled(config_entry, coordinator):
        return

    async_add_entities(
        SsdpDoorLock(coordinator, vehicle, "lock_doors")
        for vehicle in coordinator.vehicles.values()
        if should_add(hass, Platform.LOCK, f"{DOMAIN}_{vehicle.vin}_lock_doors", True)
    )


class SsdpDoorLock(SsdpEntity, LockEntity):
    _attr_icon = "mdi:car-door-lock"

    @property
    def is_locked(self) -> bool | None:
        return self.vehicle.locked

    async def async_lock(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(self._vin, remote.lock_doors())

    async def async_unlock(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(self._vin, remote.unlock_doors())
