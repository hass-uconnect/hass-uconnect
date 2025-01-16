"""Coordinator for Fiat integration"""

from __future__ import annotations

from datetime import timedelta
import traceback
import logging

from pyfiat import Client

from homeassistant.exceptions import ConfigEntryAuthFailed

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_PIN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BRAND,
    CONF_DEEP_REFRESH_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_DEEP_REFRESH_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class FiatDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.platforms: set[str] = set()

        self.client = Client(
            email=config_entry.data.get(CONF_USERNAME),
            password=config_entry.data.get(CONF_PASSWORD),
            pin=config_entry.data.get(CONF_PIN),
        )

        self.refresh_interval: int = (
            config_entry.options.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL) * 60
        )
        self.deep_refresh_interval: int = (
            config_entry.options.get(
                CONF_DEEP_REFRESH_INTERVAL, DEFAULT_DEEP_REFRESH_INTERVAL
            )
            * 60
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=self.refresh_interval
            ),
        )

    async def _async_update_data(self):
        """Update data via library. Called by update_coordinator periodically."""

        try:
            await self.hass.async_add_executor_job(self.client.refresh)
        except Exception:
            _LOGGER.exception(
                f"Update failed, falling back to cached: {
                    traceback.format_exc()}"
            )

        return self.data

    async def async_update_all(self) -> None:
        """Update vehicle data."""

        self.client.refresh()
