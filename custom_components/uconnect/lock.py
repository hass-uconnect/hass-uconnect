"""Lock for Uconnect integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Final

from homeassistant.components.lock import LockEntity, LockEntityDescription
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from py_uconnect import Command, Vehicle
from py_uconnect.command import COMMAND_DOORS_LOCK, COMMAND_DOORS_UNLOCK

from .const import CONF_ADD_COMMAND_ENTITIES, DOMAIN
from .coordinator import UconnectConfigEntry, UconnectDataUpdateCoordinator
from .entity import UconnectEntity, should_add, vehicle_name

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class UconnectLockEntityDescription(LockEntityDescription):
    """A class that describes custom lock entities."""

    icon_locked: str | None = None
    icon_unlocked: str | None = None
    command_on: Command | None = None
    command_off: Command | None = None
    is_locked: Callable[[Vehicle], bool | None] | None = None


LOCK_DESCRIPTIONS: Final[tuple[UconnectLockEntityDescription, ...]] = (
    UconnectLockEntityDescription(
        key="lock_doors",
        name="Doors Lock",
        icon_locked="mdi:car-door-lock",
        icon_unlocked="mdi:car-door-lock-open",
        command_on=COMMAND_DOORS_LOCK,
        command_off=COMMAND_DOORS_UNLOCK,
        is_locked=lambda x: getattr(x, "door_driver_locked", None),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UconnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    # Do not add entities if not configured
    if not config_entry.options.get(CONF_ADD_COMMAND_ENTITIES):
        return

    coordinator = config_entry.runtime_data
    entities: list[UconnectLock] = []
    for vehicle in coordinator.client.vehicles.values():
        for description in LOCK_DESCRIPTIONS:
            supported = any(
                cmd is not None and vehicle.supports(cmd)
                for cmd in (description.command_on, description.command_off)
            )
            if should_add(
                hass,
                Platform.LOCK,
                f"{DOMAIN}_{vehicle.vin}_{description.key}",
                supported,
            ):
                entities.append(UconnectLock(coordinator, description, vehicle))

    async_add_entities(entities)


class UconnectLock(LockEntity, UconnectEntity):
    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        description: UconnectLockEntityDescription,
        vehicle: Vehicle,
    ):
        UconnectEntity.__init__(self, coordinator, vehicle)

        self.entity_description: UconnectLockEntityDescription = description
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_{description.key}"
        self._attr_name = f"{vehicle_name(vehicle)} {description.name}"

    @property
    def icon(self):
        return (
            self.entity_description.icon_locked
            if self.is_locked
            else self.entity_description.icon_unlocked
        )

    @property
    def is_locked(self):
        return self.entity_description.is_locked(self.vehicle)

    async def async_lock(self, **kwargs):
        try:
            await self.coordinator.async_command(
                self.vehicle.vin, self.entity_description.command_on
            )
        except Exception as err:
            _LOGGER.error("Failed to lock %s: %s", self.vehicle.vin, err)
            raise HomeAssistantError(f"Failed to lock: {err}") from err

    async def async_unlock(self, **kwargs):
        try:
            await self.coordinator.async_command(
                self.vehicle.vin, self.entity_description.command_off
            )
        except Exception as err:
            _LOGGER.error("Failed to unlock %s: %s", self.vehicle.vin, err)
            raise HomeAssistantError(f"Failed to unlock: {err}") from err
