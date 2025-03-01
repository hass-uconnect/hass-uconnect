from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, CONF_ADD_COMMAND_ENTITIES
from .coordinator import UconnectDataUpdateCoordinator
from .services import async_setup_services, async_unload_services

PLATFORMS: list[str] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.SELECT,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config_entry: ConfigEntry):
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Uconnect from a config entry."""

    coordinator = UconnectDataUpdateCoordinator(hass, config_entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as e:
        raise ConfigEntryNotReady(f"Config Not Ready: {e}")

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config_entry.unique_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    async_setup_services(hass)

    # Register a listener for options updates
    config_entry.async_on_unload(
        config_entry.add_update_listener(coordinator.update_options)
    )

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
