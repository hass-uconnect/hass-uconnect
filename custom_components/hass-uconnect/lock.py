"""Lock for Uconnect integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from py_uconnect.client import Vehicle
from py_uconnect.command import COMMAND_DOORS_LOCK, COMMAND_DOORS_UNLOCK

from .const import DOMAIN
from .coordinator import UconnectDataUpdateCoordinator
from .entity import UconnectEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][config_entry.unique_id]

    entities = []
    for vehicle in coordinator.client.vehicles.values():
        entities.append(UconnectLock(coordinator, vehicle))

    async_add_entities(entities)
    return True


class UconnectLock(LockEntity, UconnectEntity):
    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
    ):
        UconnectEntity.__init__(self, coordinator, vehicle)

        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_door_lock"
        self._attr_name = f"{vehicle.make} {
            vehicle.nickname or vehicle.model} Door Lock"

    @property
    def icon(self):
        return "mdi:car-door-lock" if self.is_locked else "mdi:car-door-lock-open"

    @property
    def is_locked(self):
        return getattr(self.vehicle, "door_driver_locked")

    async def async_lock(self, **kwargs):
        await self.coordinator.async_command(self.vehicle.vin, COMMAND_DOORS_LOCK)

    async def async_unlock(self, **kwargs):
        await self.coordinator.async_command(self.vehicle.vin, COMMAND_DOORS_UNLOCK)
