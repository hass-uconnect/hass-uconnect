"""Coordinator for Uconnect integration"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_PIN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from py_uconnect import (
    APIError,
    AuthenticationError,
    ChargingLevel,
    Client,
    Command,
    CommandTimeoutError,
    PinAuthenticationError,
    UconnectError,
)
from py_uconnect.brands import BRANDS as BRANDS_BY_NAME

from .const import (
    BRANDS,
    CONF_BRAND_REGION,
    CONF_CHARGING_REFRESH_INTERVAL,
    CONF_DISABLE_TLS_VERIFICATION,
    DEFAULT_CHARGING_REFRESH_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EXTRA_DATA_INTERVAL,
    MIN_CHARGING_REFRESH_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type UconnectConfigEntry = ConfigEntry[UconnectDataUpdateCoordinator]

# HTTP statuses meaning that an endpoint is not supported by a vehicle
UNSUPPORTED_STATUSES = (400, 403, 404)


@callback
def async_get_coordinators(hass: HomeAssistant) -> list[UconnectDataUpdateCoordinator]:
    """Return the coordinators of the entries being set up or loaded."""

    return [
        coordinator
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_IN_PROGRESS)
        and isinstance(
            coordinator := getattr(entry, "runtime_data", None),
            UconnectDataUpdateCoordinator,
        )
    ]


class UconnectCommandTimeout(HomeAssistantError):
    """The vehicle did not report the result of a command in time.

    Unlike other command errors the command may still be executed.
    """


class UconnectDataUpdateCoordinator(DataUpdateCoordinator[bool]):
    """Class to manage fetching data from the API."""

    config_entry: UconnectConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: UconnectConfigEntry) -> None:
        """Initialize the coordinator."""
        self.extrapolated_soc_sensors: dict = {}

        # Data from endpoints that rarely change, refreshed less often
        self.vhr_data: dict[str, dict] = {}
        self.maintenance_data: dict[str, dict] = {}
        self.svla_data: dict[str, dict] = {}
        self._extra_data_updated: datetime | None = None
        self._unsupported: set[tuple[str, str]] = set()

        self.client = Client(
            email=config_entry.data[CONF_USERNAME],
            password=config_entry.data[CONF_PASSWORD],
            pin=self._read_pin(config_entry),
            brand=BRANDS_BY_NAME[BRANDS[config_entry.data[CONF_BRAND_REGION]]],
            session=async_create_clientsession(
                hass,
                verify_ssl=not config_entry.data.get(CONF_DISABLE_TLS_VERIFICATION),
            ),
        )

        self.charging_refresh_interval: int = self._read_charging_refresh_interval(
            config_entry
        )

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=self._read_scan_interval(config_entry),
            always_update=True,
        )

    @staticmethod
    def _read_pin(config_entry: ConfigEntry) -> str:
        """Return the PIN from the options, falling back to the setup value.

        An empty option means the field was left blank rather than cleared, so
        the PIN given during setup still applies.
        """

        return config_entry.options.get(CONF_PIN) or config_entry.data.get(CONF_PIN, "")

    @staticmethod
    def _read_scan_interval(config_entry: ConfigEntry) -> timedelta:
        """Return the polling interval."""

        return timedelta(
            minutes=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )

    @staticmethod
    def _read_charging_refresh_interval(config_entry: ConfigEntry) -> int:
        """Return the deep refresh interval while charging, in minutes.

        Zero disables the recurring refresh. Shorter intervals are raised to
        the floor because each deep refresh wakes the vehicle and keeps polling
        the command status for up to a minute.
        """

        minutes = config_entry.options.get(
            CONF_CHARGING_REFRESH_INTERVAL, DEFAULT_CHARGING_REFRESH_INTERVAL
        )

        if not isinstance(minutes, int) or minutes <= 0:
            return 0

        return max(minutes, MIN_CHARGING_REFRESH_INTERVAL)

    async def _async_update_data(self) -> bool:
        """Update data via library. Called by update_coordinator periodically."""

        first_run = self.data is None and not self.client.vehicles

        try:
            await self.client.refresh()
        except AuthenticationError as err:
            if first_run:
                raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
            _LOGGER.warning("Update failed, falling back to cached data: %s", err)
        except UconnectError as err:
            # On first run (no cached data) signal the setup failure
            if first_run:
                raise UpdateFailed(f"Initial data fetch failed: {err}") from err
            # On subsequent runs, log and fall back to cached data
            _LOGGER.warning("Update failed, falling back to cached data: %s", err)

        await self._async_update_extra_data()

        return True

    async def _async_update_extra_data(self) -> None:
        """Fetch the data that rarely changes (VHR, maintenance, SVLA).

        It is refreshed at most every EXTRA_DATA_INTERVAL, and endpoints that
        a vehicle does not support are not called again.
        """

        now = dt_util.utcnow()
        if (
            self._extra_data_updated is not None
            and now - self._extra_data_updated < EXTRA_DATA_INTERVAL
        ):
            return
        self._extra_data_updated = now

        api = self.client.api
        sources: tuple[
            tuple[str, dict[str, dict], Callable[[str], Awaitable[dict]]], ...
        ] = (
            ("health report", self.vhr_data, api.get_vehicle_health_report),
            ("maintenance history", self.maintenance_data, api.get_maintenance_history),
            ("stolen vehicle status", self.svla_data, api.get_stolen_vehicle_status),
        )

        async def fetch(
            vin: str,
            name: str,
            store: dict[str, dict],
            call: Callable[[str], Awaitable[dict]],
        ) -> None:
            if (vin, name) in self._unsupported:
                return

            try:
                store[vin] = await call(vin)
            except APIError as err:
                if err.status in UNSUPPORTED_STATUSES:
                    self._unsupported.add((vin, name))
                _LOGGER.debug("%s not available for %s: %s", name, vin, err)
            except UconnectError as err:
                _LOGGER.debug("%s not available for %s: %s", name, vin, err)

        await asyncio.gather(
            *(
                fetch(vin, name, store, call)
                for vin in self.client.vehicles
                for name, store, call in sources
            )
        )

    async def _async_call[T](self, coro: Awaitable[T], what: str) -> T:
        """Await a library call, reporting its errors as Home Assistant errors"""

        try:
            return await coro
        except PinAuthenticationError as err:
            raise HomeAssistantError(f"{what}: PIN missing or rejected: {err}") from err
        except CommandTimeoutError as err:
            raise UconnectCommandTimeout(
                f"{what}: the vehicle did not report the result in time"
            ) from err
        except UconnectError as err:
            raise HomeAssistantError(f"{what} failed: {err}") from err
        except ValueError as err:
            raise HomeAssistantError(f"{what}: {err}") from err

    async def _async_run(self, coro: Awaitable[bool], what: str) -> None:
        """Wait for the result of an operation, then refresh the data"""

        ok = await self._async_call(coro, what)

        await self.async_refresh()

        if not ok:
            raise HomeAssistantError(f"{what} failed")

    async def async_command(
        self, vin: str, cmd: Command, params: dict[str, Any] | None = None
    ) -> None:
        """Execute the given command and wait for its result"""

        await self._async_run(
            self.client.command_verify(vin, cmd, params), f"Command {cmd}"
        )

    async def async_set_charging_level(self, vin: str, level: str) -> None:
        """Set the charging level"""

        try:
            charging_level = ChargingLevel(level)
        except ValueError as err:
            raise ValueError(f"Invalid charging level: {level}") from err

        await self._async_run(
            self.client.set_charging_level_verify(vin, charging_level),
            "Set charging level",
        )

    async def async_set_charge_schedules(
        self, vin: str, schedules: list[dict[str, Any]], command: str | None = None
    ) -> None:
        """Set the charge schedules"""

        await self._async_run(
            self.client.set_charge_schedules_verify(vin, schedules, command),
            "Set charge schedule",
        )

    async def async_send_destination(
        self, vin: str, latitude: float, longitude: float, name: str | None = None
    ) -> None:
        """Send a destination to the vehicle's navigation system.

        The result is not awaited: vehicles do not report it like for commands.
        """

        await self._async_call(
            self.client.api.send_destination(vin, latitude, longitude, name),
            "Send destination",
        )

    async def update_options(
        self, hass: HomeAssistant, config_entry: UconnectConfigEntry
    ) -> None:
        """Apply changed options"""

        self.update_interval = self._read_scan_interval(config_entry)
        self.charging_refresh_interval = self._read_charging_refresh_interval(
            config_entry
        )
        self.client.set_pin(self._read_pin(config_entry))

        # A dormant deep refresh schedule has nothing left to re-arm it, so a
        # charge already under way has to be told the options allow one now
        for sensor in self.extrapolated_soc_sensors.values():
            sensor.resume_deep_refresh()
