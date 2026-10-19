"""Actions (services)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from py_uconnect import CommandTimeoutError, PinAuthenticationError, hvac_params
from py_uconnect.command import (
    COMMAND_CHARGE,
    COMMAND_CHARGE_V4,
    COMMAND_DEEP_REFRESH_V2,
    COMMAND_DOORS_LOCK,
    COMMAND_HVAC_ON,
    COMMAND_PRECOND_ON,
    TemperatureUnit,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.uconnect.const import DOMAIN
from custom_components.uconnect.coordinator import UconnectCommandTimeout

from .conftest import EV_VIN, ICE_VIN, FakeClient

# Actions registered for the fixture vehicles: those supported by at least one
EXPECTED_SERVICES = {
    "update",
    # Jeep
    "engine_on",
    "engine_off",
    "lights_horn",
    "liftgate_lock",
    "liftgate_unlock",
    # Fiat
    "precond_on",
    "precond_off",
    "lights",
    "trunk_unlock",
    "charge_now",
    "charge_now_v4",
    "deep_refresh",
    "deep_refresh_v2",
    "set_charge_schedule",
    # Both
    "doors_lock",
    "doors_unlock",
    "refresh_location",
}


def device_id(hass: HomeAssistant, vin: str) -> str:
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    return next(
        d.id
        for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        if (DOMAIN, vin) in d.identifiers
    )


async def call(hass: HomeAssistant, service: str, vin: str | None, **data: Any) -> None:
    if vin is not None:
        data["device_id"] = device_id(hass, vin)
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_registered_services(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    assert set(hass.services.async_services_for_domain(DOMAIN)) == EXPECTED_SERVICES


async def test_command(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    await call(hass, "doors_lock", ICE_VIN)

    fake_client.command_verify.assert_awaited_once_with(
        ICE_VIN, COMMAND_DOORS_LOCK, None
    )


@pytest.mark.parametrize(
    ("service", "command"),
    [
        ("charge_now", COMMAND_CHARGE),
        ("charge_now_v4", COMMAND_CHARGE_V4),
        ("deep_refresh_v2", COMMAND_DEEP_REFRESH_V2),
    ],
)
async def test_command_variants(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_client: FakeClient,
    service: str,
    command: Any,
) -> None:
    await call(hass, service, EV_VIN)

    fake_client.command_verify.assert_awaited_once_with(EV_VIN, command, None)


async def test_command_not_supported_by_vehicle(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    with pytest.raises(ServiceValidationError, match="not supported"):
        await call(hass, "precond_on", ICE_VIN)

    fake_client.command_verify.assert_not_awaited()


async def test_vehicle_required_with_several_vehicles(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError, match="vehicle must be selected"):
        await call(hass, "doors_lock", None)


async def test_single_vehicle_needs_no_device(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.list_items = [x for x in fake_client.list_items if x["vin"] == EV_VIN]
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await call(hass, "precond_on", None)

    fake_client.command_verify.assert_awaited_once_with(
        EV_VIN, COMMAND_PRECOND_ON, None
    )
    await hass.config_entries.async_unload(config_entry.entry_id)


@pytest.mark.parametrize(
    ("error", "exception", "match"),
    [
        (
            PinAuthenticationError("wrong"),
            HomeAssistantError,
            "PIN missing or rejected",
        ),
        (CommandTimeoutError("no result"), UconnectCommandTimeout, "in time"),
    ],
)
async def test_command_errors(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_client: FakeClient,
    error: Exception,
    exception: type[Exception],
    match: str,
) -> None:
    fake_client.command_verify.side_effect = error

    with pytest.raises(exception, match=match):
        await call(hass, "doors_lock", ICE_VIN)


async def test_command_reported_failure(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.command_verify.return_value = False
    refreshes = fake_client.refresh.await_count

    with pytest.raises(HomeAssistantError, match="failed"):
        await call(hass, "doors_lock", ICE_VIN)

    # The data is refreshed after a command the vehicle answered
    assert fake_client.refresh.await_count == refreshes + 1


async def test_update(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    refreshes = fake_client.refresh.await_count

    await call(hass, "update", EV_VIN)

    assert fake_client.refresh.await_count == refreshes + 1


@pytest.fixture
def climate_and_navigation(fake_client: FakeClient) -> None:
    """Give the Fiat climate control with a target temperature and navigation"""

    fake_client.add_services(EV_VIN, "ROHVACON", "ROHVACTMP", "SDV")


async def test_hvac_on_with_temperature(
    hass: HomeAssistant,
    climate_and_navigation: None,
    setup_integration: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    await call(hass, "hvac_on", EV_VIN)
    fake_client.command_verify.assert_awaited_with(EV_VIN, COMMAND_HVAC_ON, None)

    await call(hass, "hvac_on", EV_VIN, temperature=21.5)
    fake_client.command_verify.assert_awaited_with(
        EV_VIN, COMMAND_HVAC_ON, hvac_params(21.5, TemperatureUnit.CELSIUS)
    )

    hass.config.units = US_CUSTOMARY_SYSTEM
    await call(hass, "hvac_on", EV_VIN, temperature=70)
    fake_client.command_verify.assert_awaited_with(
        EV_VIN, COMMAND_HVAC_ON, hvac_params(70, TemperatureUnit.FAHRENHEIT)
    )


async def test_hvac_on_temperature_not_supported(
    hass: HomeAssistant, fake_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    fake_client.add_services(EV_VIN, "ROHVACON")
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError, match="temperature"):
        await call(hass, "hvac_on", EV_VIN, temperature=21)

    fake_client.command_verify.assert_not_awaited()
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_send_destination(
    hass: HomeAssistant,
    climate_and_navigation: None,
    setup_integration: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    await call(
        hass, "send_destination", EV_VIN, latitude=45.07, longitude=7.68, name="Home"
    )

    fake_client.api.send_destination.assert_awaited_once_with(
        EV_VIN, 45.07, 7.68, "Home"
    )


async def test_send_destination_invalid_coordinates(
    hass: HomeAssistant,
    climate_and_navigation: None,
    setup_integration: MockConfigEntry,
) -> None:
    with pytest.raises(Exception, match="latitude"):
        await call(hass, "send_destination", EV_VIN, latitude=95, longitude=7.68)


SCHEDULES = [{"scheduleType": "CHARGE", "startTime": "01:00", "endTime": "05:00"}]


@pytest.mark.parametrize(
    ("schedule", "command"),
    [
        (SCHEDULES, None),
        ({"chargeSchedulesV3": SCHEDULES}, None),
        ({"command": "CPPLUSBEV", "chargeSchedulesV3": SCHEDULES}, "CPPLUSBEV"),
    ],
)
async def test_set_charge_schedule(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_client: FakeClient,
    schedule: Any,
    command: str | None,
) -> None:
    await call(hass, "set_charge_schedule", EV_VIN, schedule=schedule)

    fake_client.set_charge_schedules_verify.assert_awaited_once_with(
        EV_VIN, SCHEDULES, command
    )


async def test_set_charge_schedule_invalid(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    with pytest.raises(ServiceValidationError, match="list of schedules"):
        await call(hass, "set_charge_schedule", EV_VIN, schedule={"foo": 1})

    fake_client.set_charge_schedules_verify.assert_not_awaited()


async def test_set_charge_schedule_unknown_service(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.set_charge_schedules_verify.side_effect = ValueError(
        "no schedule service known"
    )

    with pytest.raises(HomeAssistantError, match="no schedule service"):
        await call(hass, "set_charge_schedule", EV_VIN, schedule=SCHEDULES)
