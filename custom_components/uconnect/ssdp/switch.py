"""Switches of the SSDP vehicles: climate preconditioning and charging"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from stellantis_ssdp import RemoteCommand, Vehicle, remote

from ..const import DOMAIN
from ..coordinator import UconnectConfigEntry
from ..entity import should_add
from .coordinator import SsdpDataUpdateCoordinator
from .entity import SsdpEntity, command_entities_enabled
from .vehicle import has_battery


@dataclass(frozen=True, kw_only=True)
class SsdpSwitchEntityDescription(SwitchEntityDescription):
    """A switch that sends a remote command"""

    command: Callable[[bool], RemoteCommand]
    is_on: Callable[[Vehicle], bool | None]
    supported: Callable[[Vehicle], bool] = lambda v: True


SWITCHES: tuple[SsdpSwitchEntityDescription, ...] = (
    SsdpSwitchEntityDescription(
        # Remote engine start: the vehicle list has no capability flags, a
        # vehicle without it reports a failure cause
        key="switch_engine",
        icon="mdi:engine",
        command=remote.engine,
        is_on=lambda v: v.ignition_on,
    ),
    SsdpSwitchEntityDescription(
        key="switch_precondition",
        icon="mdi:air-conditioner",
        command=remote.preconditioning,
        is_on=lambda v: v.preconditioning_on,
    ),
    SsdpSwitchEntityDescription(
        key="switch_charging",
        icon="mdi:ev-station",
        command=remote.charge_now,
        is_on=lambda v: v.charging,
        supported=has_battery,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UconnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SsdpDataUpdateCoordinator = config_entry.runtime_data  # type: ignore[assignment]
    if not command_entities_enabled(config_entry, coordinator):
        return

    async_add_entities(
        SsdpSwitch(coordinator, vehicle, description)
        for vehicle in coordinator.vehicles.values()
        for description in SWITCHES
        if should_add(
            hass,
            Platform.SWITCH,
            f"{DOMAIN}_{vehicle.vin}_{description.key}",
            description.supported(vehicle),
        )
    )


class SsdpSwitch(SsdpEntity, SwitchEntity):
    entity_description: SsdpSwitchEntityDescription

    def __init__(
        self,
        coordinator: SsdpDataUpdateCoordinator,
        vehicle: Vehicle,
        description: SsdpSwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator, vehicle, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on(self.vehicle)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(
            self._vin, self.entity_description.command(True)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(
            self._vin, self.entity_description.command(False)
        )
