"""Coordinator for Uconnect integration"""

from __future__ import annotations

from datetime import timedelta
import traceback
import logging

from py_uconnect import Client
from py_uconnect.command import Command
from py_uconnect.api import CHARGING_LEVELS_BY_NAME
from py_uconnect.brands import BRANDS as BRANDS_BY_NAME

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_PIN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_BRAND_REGION,
    CONF_DISABLE_TLS_VERIFICATION,
    BRANDS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(DOMAIN)


class UconnectDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.platforms: set[str] = set()

        self.client = Client(
            email=config_entry.data.get(CONF_USERNAME),
            password=config_entry.data.get(CONF_PASSWORD),
            pin=config_entry.data.get(CONF_PIN),
            brand=BRANDS_BY_NAME[BRANDS[config_entry.data.get(CONF_BRAND_REGION)]],
            disable_tls_verification=config_entry.data.get(
                CONF_DISABLE_TLS_VERIFICATION
            ),
        )

        self.refresh_interval: int = (
            config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL) * 60
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=self.refresh_interval),
            always_update=True,
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

    async def async_command(self, vin: str, cmd: Command) -> None:
        """Execute the given command"""

        r = await self.hass.async_add_executor_job(self.client.command_verify, vin, cmd)
        await self.async_refresh()

        if not r:
            raise Exception("Command execution failed")

    async def async_set_charging_level(self, vin: str, level: str) -> None:
        """Set the charging level"""

        level = CHARGING_LEVELS_BY_NAME[level]

        r = await self.hass.async_add_executor_job(
            self.client.set_charging_level_verify, vin, level
        )
        await self.async_refresh()

        if not r:
            raise Exception("Set charging level failed")

    async def update_options(self, hass: HomeAssistant, config_entry: ConfigEntry):
        self.update_interval = timedelta(
            seconds=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            * 60
        )
