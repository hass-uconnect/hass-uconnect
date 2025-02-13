"""Lock for Uconnect integration."""

from __future__ import annotations
from typing import Callable, Final

from homeassistant.core import HomeAssistant
from homeassistant.components.lock import LockEntity, LockEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from py_uconnect.client import Vehicle
from py_uconnect.command import *

from .const import DOMAIN
from .coordinator import UconnectDataUpdateCoordinator
from .entity import UconnectEntity


@dataclass
class UconnectLockEntityDescription(LockEntityDescription):
    """A class that describes custom lock entities."""

    icon_locked: str = None
    icon_unlocked: str = None
    command_on: Command = None
    command_off: Command = None
    is_locked: Callable[[Vehicle], bool] | None = None


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
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][config_entry.unique_id]
    coordinator: UconnectDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.unique_id
    ]
    entities: list[UconnectLock] = []

    entities = []
    for vehicle in coordinator.client.vehicles.values():
        for description in LOCK_DESCRIPTIONS:
            if (
                description.command_on.name in vehicle.supported_commands
                or description.command_off.name in vehicle.supported_commands
            ) and description.is_locked(vehicle) is not None:

                entities.append(UconnectLock(coordinator, description, vehicle))

    async_add_entities(entities)
    return True


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
        self._attr_name = f"{vehicle.make} {
            vehicle.nickname or vehicle.model} {description.name}"

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
        await self.coordinator.async_command(
            self.vehicle.vin, self.entity_description.command_on
        )

    async def async_unlock(self, **kwargs):
        await self.coordinator.async_command(
            self.vehicle.vin, self.entity_description.command_off
        )
