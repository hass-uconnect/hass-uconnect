"""Coordinator refresh and command handling."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from py_uconnect import APIError, AuthenticationError, UconnectConnectionError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.uconnect.const import DOMAIN
from custom_components.uconnect.coordinator import UconnectCommandTimeout

from .conftest import EV_VIN, ICE_VIN, FakeClient


@pytest.mark.parametrize(
    "error", [UconnectConnectionError("timeout"), AuthenticationError("rejected")]
)
async def test_later_failures_keep_cached_data(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_client: FakeClient,
    error: Exception,
) -> None:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{DOMAIN}_{EV_VIN}_state_of_charge"
    )
    fake_client.refresh.side_effect = error

    coordinator = setup_integration.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success
    assert hass.states.get(entity_id).state == "63.0"
    # No reauth for an error after the setup, it may be temporary
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_extra_data_is_throttled(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_client: FakeClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    coordinator = setup_integration.runtime_data
    vhr = fake_client.api.get_vehicle_health_report
    assert vhr.await_count == 2

    freezer.tick(timedelta(minutes=10))
    await coordinator.async_refresh()
    assert vhr.await_count == 2

    freezer.tick(timedelta(minutes=21))
    await coordinator.async_refresh()
    assert vhr.await_count == 4


async def test_unsupported_extra_data_is_skipped(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: FakeClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    async def svla(vin: str) -> dict:
        if vin == ICE_VIN:
            raise APIError("not found", status=404)
        return {"svlaStatus": False}

    fake_client.api.get_stolen_vehicle_status.side_effect = svla
    fake_client.api.get_maintenance_history.side_effect = APIError(
        "server error", status=500
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = config_entry.runtime_data
    assert set(coordinator.svla_data) == {EV_VIN}
    assert coordinator.maintenance_data == {}

    freezer.tick(timedelta(minutes=31))
    await coordinator.async_refresh()

    # Unsupported (404) is not asked again, other errors are retried
    svla_vins = [
        c.args[0] for c in fake_client.api.get_stolen_vehicle_status.await_args_list
    ]
    assert svla_vins.count(ICE_VIN) == 1
    assert svla_vins.count(EV_VIN) == 2
    assert fake_client.api.get_maintenance_history.await_count == 4

    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_entity_kept_when_extra_data_fails_later(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_client: FakeClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{DOMAIN}_{EV_VIN}_vhr"
    )
    fake_client.api.get_vehicle_health_report.side_effect = UconnectConnectionError(
        "timeout"
    )

    freezer.tick(timedelta(minutes=31))
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("error", "refreshed"),
    [
        # Unanswered: the command may still be executed, read again
        (UconnectCommandTimeout("no result"), True),
        (RuntimeError("unexpected"), True),
        # Refused: nothing to read
        (HomeAssistantError("failed"), False),
    ],
)
async def test_deep_refresh_failures(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    error: Exception,
    refreshed: bool,
) -> None:
    coordinator = setup_integration.runtime_data
    sensor = coordinator.extrapolated_soc_sensors[EV_VIN]

    # The vehicle has DEEPREFRESH2 only, which now enables the deep refresh
    assert sensor._can_deep_refresh()

    coordinator.async_command = AsyncMock(side_effect=error)
    coordinator.async_request_refresh = AsyncMock()

    await sensor._async_do_deep_refresh()

    assert coordinator.async_request_refresh.await_count == (1 if refreshed else 0)


async def test_no_deep_refresh_without_pin(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.set_pin("")
    sensor = setup_integration.runtime_data.extrapolated_soc_sensors[EV_VIN]

    assert not sensor._can_deep_refresh()
