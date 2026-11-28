"""Buttons of the SSDP vehicles"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from stellantis_ssdp import RemoteCommand, Vehicle, remote

from ..const import CONF_ADD_COMMAND_ENTITIES, DOMAIN
from ..coordinator import UconnectConfigEntry
from ..entity import should_add
from .coordinator import SsdpDataUpdateCoordinator
from .entity import SsdpEntity, command_entities_enabled


@dataclass(frozen=True, kw_only=True)
class SsdpButtonEntityDescription(ButtonEntityDescription):
    """A button that sends a remote command"""

    command: Callable[[], RemoteCommand]


BUTTONS: tuple[SsdpButtonEntityDescription, ...] = (
    SsdpButtonEntityDescription(
        key="button_lights", icon="mdi:car-light-high", command=remote.lights
    ),
    SsdpButtonEntityDescription(
        key="button_horn", icon="mdi:bullhorn", command=remote.horn
    ),
    SsdpButtonEntityDescription(
        key="button_deep_refresh", icon="mdi:refresh", command=remote.wakeup
    ),
    SsdpButtonEntityDescription(
        key="button_location", icon="mdi:map-marker-radius", command=remote.locate
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UconnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SsdpDataUpdateCoordinator = config_entry.runtime_data  # type: ignore[assignment]

    # Like for Uconnect: the button that refreshes the data comes with the
    # command entities, it needs no remote-command setup
    if not config_entry.options.get(CONF_ADD_COMMAND_ENTITIES):
        return

    entities: list[ButtonEntity] = [
        SsdpUpdateButton(coordinator, vehicle, "update")
        for vehicle in coordinator.vehicles.values()
    ]

    if command_entities_enabled(config_entry, coordinator):
        entities.extend(
            SsdpCommandButton(coordinator, vehicle, description)
            for vehicle in coordinator.vehicles.values()
            for description in BUTTONS
            if should_add(
                hass,
                Platform.BUTTON,
                f"{DOMAIN}_{vehicle.vin}_{description.key}",
                True,
            )
        )

    async_add_entities(entities)


class SsdpCommandButton(SsdpEntity, ButtonEntity):
    entity_description: SsdpButtonEntityDescription

    def __init__(
        self,
        coordinator: SsdpDataUpdateCoordinator,
        vehicle: Vehicle,
        description: SsdpButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator, vehicle, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self.coordinator.async_command(
            self._vin, self.entity_description.command()
        )


class SsdpUpdateButton(SsdpEntity, ButtonEntity):
    """Fetches the data now"""

    _attr_icon = "mdi:update"

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()
