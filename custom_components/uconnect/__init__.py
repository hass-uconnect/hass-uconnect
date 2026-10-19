"""The Uconnect integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import (
    UconnectConfigEntry,
    UconnectDataUpdateCoordinator,
    async_get_coordinators,
)
from .frontend_cards import (
    async_setup_frontend_cards,
    async_unload_frontend_cards_if_last_entry,
)
from .services import async_setup_services, async_unload_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.IMAGE,
    Platform.LOCK,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.SELECT,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Uconnect integration."""
    return True


async def async_setup_entry(
    hass: HomeAssistant, config_entry: UconnectConfigEntry
) -> bool:
    """Set up Uconnect from a config entry."""

    coordinator = UconnectDataUpdateCoordinator(hass, config_entry)

    # Raises ConfigEntryNotReady, or ConfigEntryAuthFailed to start reauth
    await coordinator.async_config_entry_first_refresh()

    config_entry.runtime_data = coordinator
    await async_setup_frontend_cards(hass)
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    async_setup_services(hass)

    config_entry.async_on_unload(
        config_entry.add_update_listener(coordinator.update_options)
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant, config_entry: UconnectConfigEntry
) -> bool:
    """Unload a config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )

    if unload_ok:
        remaining = [
            c
            for c in async_get_coordinators(hass)
            if c.config_entry.entry_id != config_entry.entry_id
        ]
        if not remaining:
            async_unload_services(hass)
            await async_unload_frontend_cards_if_last_entry(hass)
        else:
            async_setup_services(hass)

    return unload_ok
