"""Coordinator for the entries of SSDP brands"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from stellantis_ssdp import (
    AuthenticationError,
    Client,
    CommandError,
    CommandTimeoutError,
    RemoteAuthenticationError,
    RemoteCommand,
    SSDPError,
    State,
    Vehicle,
)

from ..const import (
    BRANDS,
    CONF_ADD_COMMAND_ENTITIES,
    CONF_BRAND_REGION,
    CONF_DISABLE_TLS_VERIFICATION,
    CONF_SSDP_STATE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SSDP_BRANDS,
)
from ..coordinator import (
    UconnectCommandTimeout,
    UconnectDataUpdateCoordinator,
    normalize_vehicle_numbers,
)

if TYPE_CHECKING:
    from ..coordinator import UconnectConfigEntry

_LOGGER = logging.getLogger(__name__)


@callback
def async_get_all_coordinators(
    hass: HomeAssistant,
) -> list[UconnectDataUpdateCoordinator | SsdpDataUpdateCoordinator]:
    """Return the coordinators of all the entries being set up or loaded,
    of both backends"""

    return [
        coordinator
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_IN_PROGRESS)
        and isinstance(
            coordinator := getattr(entry, "runtime_data", None),
            UconnectDataUpdateCoordinator | SsdpDataUpdateCoordinator,
        )
    ]


class SsdpDataUpdateCoordinator(DataUpdateCoordinator[bool]):
    """Fetches the data of an SSDP account and runs remote commands"""

    config_entry: UconnectConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: UconnectConfigEntry) -> None:
        # Vehicles shown by this entry: those of the account that no other
        # entry provides (see _update_vehicles)
        self.vehicles: dict[str, Vehicle] = {}
        self._skipped: set[str] = set()
        self._warned_no_vehicles = False

        data = config_entry.data
        self.client = Client(
            SSDP_BRANDS[data[CONF_BRAND_REGION]],
            State.from_dict(data[CONF_SSDP_STATE]),
            pin=UconnectDataUpdateCoordinator._read_pin(config_entry),
            session=async_create_clientsession(
                hass, verify_ssl=not data.get(CONF_DISABLE_TLS_VERIFICATION)
            ),
            on_state_change=self._save_state,
            email=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
        )

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=self._read_scan_interval(config_entry),
            always_update=True,
        )

        # Whether the platforms add the command entities, they are added by a
        # reload when this changes
        self.command_entities = self._command_entities_enabled(config_entry)

    def _command_entities_enabled(self, config_entry: UconnectConfigEntry) -> bool:
        return (
            bool(config_entry.options.get(CONF_ADD_COMMAND_ENTITIES))
            and self.client.enrolled
        )

    @staticmethod
    def _read_scan_interval(config_entry: UconnectConfigEntry) -> timedelta:
        return timedelta(
            minutes=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )

    @property
    def enrolled(self) -> bool:
        """Whether remote commands are set up"""

        return self.client.enrolled

    @callback
    def _save_state(self, state: State) -> None:
        """Persist the tokens and the soft token: they change as tokens are
        renewed, and the soft token can only be set up again with an SMS"""

        entry = self.config_entry
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_SSDP_STATE: state.to_dict()}
        )

    async def _async_update_data(self) -> bool:
        first_run = self.data is None

        try:
            await self.client.refresh()
        except AuthenticationError as err:
            # The library already tried to log in again with the password
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except SSDPError as err:
            if first_run:
                raise UpdateFailed(f"Initial data fetch failed: {err}") from err
            _LOGGER.warning("Update failed, falling back to cached data: %s", err)
        else:
            self._warn_if_no_vehicles()

        # Also after a failure: the vehicles may have been partly updated
        for vehicle in self.client.vehicles.values():
            normalize_vehicle_numbers(vehicle)

        self._update_vehicles()

        return True

    def _update_vehicles(self) -> None:
        """Expose the vehicles that no other entry provides.

        One Stellantis account may list the vehicles of several brands, and a
        VIN could also be in a Uconnect account: two entries providing the
        same vehicle would create the same device and entity IDs. A vehicle
        stays with the Uconnect entry, or with the SSDP entry that shows it
        already or has the smallest entry ID.
        """

        own_id = self.config_entry.entry_id
        taken: set[str] = set()
        for other in async_get_all_coordinators(self.hass):
            if other is self:
                continue
            if isinstance(other, UconnectDataUpdateCoordinator):
                taken.update(other.client.vehicles)
            else:
                taken.update(other.vehicles)
                if other.config_entry.entry_id < own_id:
                    taken.update(other.client.vehicles)

        vehicles: dict[str, Vehicle] = {}
        for vin, vehicle in self.client.vehicles.items():
            if vin in taken and vin not in self.vehicles:
                if vin not in self._skipped:
                    self._skipped.add(vin)
                    _LOGGER.warning(
                        "Vehicle %s of the %s account is already provided by "
                        "another entry, it is not added again",
                        vin,
                        BRANDS[self.config_entry.data[CONF_BRAND_REGION]],
                    )
                continue
            vehicles[vin] = vehicle

        self.vehicles = vehicles

    def _warn_if_no_vehicles(self) -> None:
        if self.client.vehicles:
            self._warned_no_vehicles = False
            return

        if not self._warned_no_vehicles:
            self._warned_no_vehicles = True
            _LOGGER.warning(
                "No vehicles found in the %s account. Only the vehicles shown in "
                "the brand's 2.0 app use this service",
                BRANDS[self.config_entry.data[CONF_BRAND_REGION]],
            )

    async def _async_call[T](self, coro: Awaitable[T], what: str) -> T:
        """Await a library call, reporting its errors as Home Assistant errors"""

        try:
            return await coro
        except RemoteAuthenticationError as err:
            raise HomeAssistantError(
                f"{what}: remote commands are not authorized ({err}). Check the "
                "PIN, or set up remote commands again in the integration options"
            ) from err
        except CommandTimeoutError as err:
            raise UconnectCommandTimeout(
                f"{what}: the vehicle did not report the result in time"
            ) from err
        except (CommandError, SSDPError) as err:
            raise HomeAssistantError(f"{what} failed: {err}") from err

    async def async_command(self, vin: str, cmd: RemoteCommand) -> None:
        """Send a remote command, wait for its result, then refresh the data"""

        try:
            await self._async_call(
                self.client.command_verify(vin, cmd), f"Command {cmd.action}"
            )
        finally:
            await self.async_request_refresh()

    async def update_options(
        self, hass: HomeAssistant, config_entry: UconnectConfigEntry
    ) -> None:
        """Apply changed options"""

        self.update_interval = self._read_scan_interval(config_entry)
        self.client.set_pin(UconnectDataUpdateCoordinator._read_pin(config_entry))

        # Remote commands were set up, or the command entities option changed
        if self._command_entities_enabled(config_entry) != self.command_entities:
            self.command_entities = not self.command_entities
            hass.config_entries.async_schedule_reload(config_entry.entry_id)
