"""The Uconnect integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .config_flow import entry_unique_id
from .const import BRANDS, CONF_BRAND_REGION, DOMAIN, is_ssdp_brand
from .coordinator import (
    UconnectConfigEntry,
    UconnectDataUpdateCoordinator,
)
from .frontend_cards import (
    async_setup_frontend_cards,
    async_unload_frontend_cards_if_last_entry,
)
from .services import async_setup_services, async_unload_services
from .ssdp.coordinator import SsdpDataUpdateCoordinator, async_get_all_coordinators

_LOGGER = logging.getLogger(__name__)

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


def warn_if_changed_by_reauth(config_entry: ConfigEntry) -> None:
    """Warn if the brand or username of the entry differs from its setup.

    The unique ID is derived from the brand and username the entry was set up
    with. The re-authentication form of earlier versions asked for them again
    and could change them without updating the title, so the entry used
    another brand or account than its title shows and could get no vehicles.
    """

    username = config_entry.data[CONF_USERNAME]
    brand = BRANDS[config_entry.data[CONF_BRAND_REGION]]

    if config_entry.unique_id in (
        None,
        entry_unique_id(config_entry.data[CONF_BRAND_REGION], username),
    ):
        return

    original = next(
        (
            name
            for number, name in BRANDS.items()
            if entry_unique_id(number, username) == config_entry.unique_id
        ),
        None,
    )

    # The username is not logged, it is an email address
    if original:
        _LOGGER.warning(
            "This Uconnect entry was set up for %s but logs in with %s, which a "
            "re-authentication changed. If its vehicles are missing, remove the "
            "entry and add it again with %s",
            original,
            brand,
            original,
        )
    else:
        _LOGGER.warning(
            "This %s Uconnect entry logs in with another username than it was set "
            "up with, which a re-authentication changed. If its vehicles are "
            "missing, remove the entry and add it again",
            brand,
        )


async def async_setup_entry(
    hass: HomeAssistant, config_entry: UconnectConfigEntry
) -> bool:
    """Set up Uconnect from a config entry."""

    warn_if_changed_by_reauth(config_entry)

    coordinator: UconnectDataUpdateCoordinator | SsdpDataUpdateCoordinator
    if is_ssdp_brand(config_entry.data[CONF_BRAND_REGION]):
        coordinator = SsdpDataUpdateCoordinator(hass, config_entry)
    else:
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
        # The entries left, of both backends: the actions and the vehicle card
        # are shared by their vehicles
        remaining = [
            c
            for c in async_get_all_coordinators(hass)
            if c.config_entry.entry_id != config_entry.entry_id
        ]
        if not remaining:
            async_unload_services(hass)
            await async_unload_frontend_cards_if_last_entry(hass)
        else:
            async_setup_services(hass)

    return unload_ok
