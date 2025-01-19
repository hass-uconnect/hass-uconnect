import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import FiatDataUpdateCoordinator
from .services import async_setup_services, async_unload_services

PLATFORMS: list[str] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config_entry: ConfigEntry):
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Fiat from a config entry."""

    coordinator = FiatDataUpdateCoordinator(hass, config_entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as ex:
        raise ConfigEntryNotReady(f"Config Not Ready: {ex}")

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config_entry.unique_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    async_setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    if unload_ok := await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    ):
        del hass.data[DOMAIN][config_entry.unique_id]

    if not hass.data[DOMAIN]:
        async_unload_services(hass)

    return unload_ok
