"""Entries of the SSDP brands (Jeep 2.0 and the other brands' 2.0 apps)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_PIN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from py_uconnect.command import COMMAND_DOORS_LOCK
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import stellantis_ssdp
from stellantis_ssdp import (
    AuthenticationError,
    CommandError,
    CommandTimeoutError,
    RemoteAuthenticationError,
    SSDPConnectionError,
    State,
    remote,
)

from custom_components.uconnect.config_flow import entry_unique_id
from custom_components.uconnect.const import (
    CONF_ADD_COMMAND_ENTITIES,
    CONF_BRAND_REGION,
    CONF_SSDP_STATE,
    DOMAIN,
)
from custom_components.uconnect.coordinator import (
    UconnectCommandTimeout,
    async_get_coordinators,
)
from custom_components.uconnect.frontend_cards import _build_vehicle_list

from .conftest import (
    EV_VIN,
    ICE_VIN,
    SSDP_BRAND,
    SSDP_USER_ID,
    SSDP_VIN,
    FakeClient,
    FakeSsdpClientFactory,
    make_ssdp_entry,
    make_ssdp_state,
    make_ssdp_token,
)

USER_INPUT = {
    "username": "user@example.com",
    "password": "secret",
    "brand_region": SSDP_BRAND,
    "pin": "1234",
    "disable_tls_verification": False,
}

SENSORS = {
    "state_of_charge",
    "distance_to_empty",
    "range_gas",
    "range_total",
    "fuel_amount",
    "odometer",
    "days_to_service",
    "distance_to_service",
    "battery_voltage",
    "battery_12v_level",
    "battery_health",
    "battery_temperature",
    "charging_status",
    "fuel_type",
    "privacy_mode",
    "timestamp_status",
}
BINARY_SENSORS = {
    "ignition_on",
    "plugged_in",
    "charging",
    "hvac_on",
    "doors_locked",
    "moving",
    "door_driver_open",
    "door_passenger_open",
    "door_rear_left_open",
    "door_rear_right_open",
    "hood_open",
    "rear_window_open",
    "wheel_front_left_pressure_warning",
    "wheel_front_right_pressure_warning",
    "wheel_rear_left_pressure_warning",
    "wheel_rear_right_pressure_warning",
}
COMMAND_ENTITIES = {
    Platform.LOCK: {"lock_doors"},
    Platform.SWITCH: {"switch_engine", "switch_precondition", "switch_charging"},
    Platform.BUTTON: {
        "button_lights",
        "button_horn",
        "button_deep_refresh",
        "button_location",
    },
}


def registered(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, set[str]]:
    """The keys of the entities of an entry, per platform"""

    prefix = f"{DOMAIN}_{SSDP_VIN}_"
    result: dict[str, set[str]] = {}
    for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        assert e.unique_id.startswith(prefix)
        result.setdefault(e.domain, set()).add(e.unique_id.removeprefix(prefix))
    return result


def entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    eid = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{DOMAIN}_{SSDP_VIN}_{key}"
    )
    assert eid is not None, key
    return eid


def state(hass: HomeAssistant, platform: str, key: str) -> Any:
    s = hass.states.get(entity_id(hass, platform, key))
    assert s is not None
    return s


# --- Config flow -----------------------------------------------------------------


@pytest.fixture
def login() -> Any:
    mock = AsyncMock(return_value=make_ssdp_token("NEW"))
    with patch("custom_components.uconnect.config_flow.password_login", mock):
        yield mock


@pytest.fixture
def flow_client() -> Any:
    factory = FakeSsdpClientFactory()
    with patch.object(stellantis_ssdp, "Client", factory):
        yield factory


async def start_flow(hass: HomeAssistant, user_input: dict[str, Any]) -> Any:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


@pytest.fixture
def no_setup() -> Any:
    with patch("custom_components.uconnect.async_setup_entry", return_value=True):
        yield


@pytest.mark.usefixtures("no_setup")
async def test_user_flow_without_remote_commands(
    hass: HomeAssistant, login: AsyncMock
) -> None:
    result = await start_flow(hass, USER_INPUT)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "ssdp_remote"
    assert result["menu_options"] == ["ssdp_send_sms", "ssdp_finish"]
    assert login.call_args.args[0] is stellantis_ssdp.JEEP_EU
    assert login.call_args.args[1:] == ("user@example.com", "secret")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "ssdp_finish"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "JEEP_EU_SSDP user@example.com"
    entry = result["result"]
    assert entry.unique_id == entry_unique_id(SSDP_BRAND, "user@example.com")
    assert entry.options == {}
    state = State.from_dict(entry.data[CONF_SSDP_STATE])
    assert state.token.access_token == "NEW"
    assert not state.enrolled
    assert {k: v for k, v in entry.data.items() if k != CONF_SSDP_STATE} == USER_INPUT


@pytest.mark.usefixtures("no_setup", "login")
async def test_user_flow_with_remote_commands(
    hass: HomeAssistant, flow_client: FakeSsdpClientFactory
) -> None:
    result = await start_flow(hass, USER_INPUT)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "ssdp_send_sms"}
    )

    client = flow_client.last
    client.enroll_start.assert_awaited_once()
    assert client.state.token.access_token == "NEW"
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "ssdp_enroll"

    # A wrong code can be corrected
    client.enroll_finish.side_effect = [
        RemoteAuthenticationError("wrong activation code"),
        None,
    ]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"sms_code": "000000", "pin": "1234"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_code"}

    client.enroll_finish.side_effect = client._enroll_finish
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"sms_code": " 123456 ", "pin": "9999"}
    )

    client.enroll_finish.assert_awaited_with("123456", "9999")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.data[CONF_PIN] == "9999"
    assert entry.options == {CONF_ADD_COMMAND_ENTITIES: True}
    assert State.from_dict(entry.data[CONF_SSDP_STATE]).enrolled


@pytest.mark.usefixtures("no_setup", "login")
async def test_user_flow_sms_retry(
    hass: HomeAssistant, flow_client: FakeSsdpClientFactory
) -> None:
    result = await start_flow(hass, USER_INPUT)

    with patch.object(
        FakeSsdpClientFactory,
        "__call__",
        side_effect=lambda *a, **kw: _failing_sms_client(flow_client, a, kw),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "ssdp_send_sms"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "ssdp_send_sms"
    assert result["errors"] == {"base": "cannot_connect"}

    # Submitting the form sends the SMS again
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "ssdp_enroll"
    assert flow_client.last.enroll_start.await_count == 2


def _failing_sms_client(
    factory: FakeSsdpClientFactory, args: tuple[Any, ...], kwargs: Any
) -> Any:
    from .conftest import FakeSsdpClient

    client = FakeSsdpClient(factory, args, kwargs)
    client.enroll_start.side_effect = [SSDPConnectionError("down"), None]
    factory.instances.append(client)
    return client


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AuthenticationError("wrong password"), "invalid_auth"),
        (SSDPConnectionError("down"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_login_errors(
    hass: HomeAssistant, login: AsyncMock, error: Exception, reason: str
) -> None:
    login.side_effect = error

    result = await start_flow(hass, USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": reason}


async def test_user_flow_already_configured(
    hass: HomeAssistant, login: AsyncMock, flow_client: FakeSsdpClientFactory
) -> None:
    make_ssdp_entry().add_to_hass(hass)

    result = await start_flow(hass, USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # No SMS for an account that is already set up
    assert flow_client.instances == []


@pytest.mark.usefixtures("no_setup", "login")
async def test_coexists_with_uconnect_entry(hass: HomeAssistant) -> None:
    """A Uconnect JEEP_EU entry and a JEEP_EU_SSDP entry of the same account"""

    MockConfigEntry(
        domain=DOMAIN,
        title="JEEP_EU user@example.com",
        unique_id=entry_unique_id(5, "user@example.com"),
        data={**USER_INPUT, "brand_region": 5},
    ).add_to_hass(hass)

    result = await start_flow(hass, USER_INPUT)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "ssdp_finish"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2


@pytest.mark.usefixtures("no_setup")
async def test_user_flow_other_brand(hass: HomeAssistant, login: AsyncMock) -> None:
    result = await start_flow(hass, {**USER_INPUT, "brand_region": 22})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "ssdp_finish"}
    )

    assert login.call_args.args[0] is stellantis_ssdp.PEUGEOT_EU
    assert result["title"] == "PEUGEOT_EU_SSDP user@example.com"


async def test_reauth_keeps_remote_commands(
    hass: HomeAssistant,
    ssdp_config_entry: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
    login: AsyncMock,
) -> None:
    original = State.from_dict(ssdp_config_entry.data[CONF_SSDP_STATE])

    with patch.object(
        FakeSsdpClientFactory,
        "__call__",
        side_effect=lambda *a, **kw: _auth_failing_client(ssdp_client, a, kw),
    ):
        await hass.config_entries.async_setup(ssdp_config_entry.entry_id)
        await hass.async_block_till_done()

    assert ssdp_config_entry.state is ConfigEntryState.SETUP_ERROR
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"]["source"] == "reauth"

    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_PASSWORD: "new-secret"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert login.call_args.args[1:] == ("user@example.com", "new-secret")
    assert ssdp_config_entry.data[CONF_PASSWORD] == "new-secret"
    state = State.from_dict(ssdp_config_entry.data[CONF_SSDP_STATE])
    assert state.token.access_token == "NEW"
    assert state.soft_token == original.soft_token
    assert ssdp_config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(ssdp_config_entry.entry_id)


def _auth_failing_client(
    factory: FakeSsdpClientFactory, args: tuple[Any, ...], kwargs: Any
) -> Any:
    from .conftest import FakeSsdpClient

    client = FakeSsdpClient(factory, args, kwargs)
    if len(factory.instances) == 0:
        client.refresh.side_effect = AuthenticationError("refresh token rejected")
    factory.instances.append(client)
    return client


# --- Options -----------------------------------------------------------------------


async def test_options_settings(
    hass: HomeAssistant,
    setup_ssdp_integration: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
) -> None:
    entry = setup_ssdp_integration

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "ssdp_menu"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "ssdp_settings"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"scan_interval": 10, "pin": "4321", CONF_ADD_COMMAND_ENTITIES: True},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["scan_interval"] == 10
    assert entry.runtime_data.update_interval.total_seconds() == 600
    ssdp_client.last.set_pin.assert_called_with("4321")


async def test_options_set_up_remote_commands(
    hass: HomeAssistant, ssdp_client: FakeSsdpClientFactory
) -> None:
    entry = make_ssdp_entry(enrolled=False, command_entities=False)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert Platform.LOCK not in registered(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "ssdp_send_sms"}
    )
    ssdp_client.last.enroll_start.assert_awaited_once()
    assert result["step_id"] == "ssdp_enroll"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"sms_code": "123456", "pin": "5555"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ADD_COMMAND_ENTITIES] is True
    assert entry.options[CONF_PIN] == "5555"
    assert State.from_dict(entry.data[CONF_SSDP_STATE]).enrolled

    # The entry was reloaded with the command entities
    assert entry.state is ConfigEntryState.LOADED
    assert len(ssdp_client.instances) == 2
    entities = registered(hass, entry)
    for platform, keys in COMMAND_ENTITIES.items():
        assert keys <= entities[platform]

    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_remote_commands_need_loaded_entry(
    hass: HomeAssistant, ssdp_config_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(ssdp_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "ssdp_send_sms"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"


# --- Entities ----------------------------------------------------------------------


async def test_entities(
    hass: HomeAssistant, setup_ssdp_integration: MockConfigEntry
) -> None:
    assert registered(hass, setup_ssdp_integration) == {
        Platform.SENSOR: SENSORS,
        Platform.BINARY_SENSOR: BINARY_SENSORS,
        Platform.DEVICE_TRACKER: {"location"},
        Platform.BUTTON: {"update"} | COMMAND_ENTITIES[Platform.BUTTON],
        Platform.LOCK: COMMAND_ENTITIES[Platform.LOCK],
        Platform.SWITCH: COMMAND_ENTITIES[Platform.SWITCH],
    }

    [device] = dr.async_entries_for_config_entry(
        dr.async_get(hass), setup_ssdp_integration.entry_id
    )
    assert device.identifiers == {(DOMAIN, SSDP_VIN)}
    assert device.name == "JEEP Compass"
    assert device.manufacturer == "JEEP"
    assert device.model == "Compass"

    sensors = {
        "state_of_charge": "49",
        "distance_to_empty": "22",
        "range_gas": "432",
        "range_total": "454",
        "fuel_amount": "48",
        "odometer": "997.2",
        "days_to_service": "343",
        "distance_to_service": "24000",
        "battery_voltage": "13.83",
        "battery_12v_level": "93",
        "battery_health": "99",
        "battery_temperature": "14",
        "charging_status": "InProgress",
        "fuel_type": "PHEV",
        "privacy_mode": "None",
        "timestamp_status": "2026-11-26T21:16:59+00:00",
    }
    for key, value in sensors.items():
        assert state(hass, "sensor", key).state == value, key

    assert state(hass, "sensor", "odometer").attributes["unit_of_measurement"] == "km"
    assert (
        state(hass, "sensor", "state_of_charge").name == "JEEP Compass HVBattery Charge"
    )

    binary = {
        "plugged_in": "on",
        "charging": "on",
        "hvac_on": "off",
        "doors_locked": "off",
        "ignition_on": "off",
        "moving": "off",
        "hood_open": "off",
        "door_driver_open": "off",
        "wheel_front_left_pressure_warning": "off",
    }
    for key, value in binary.items():
        assert state(hass, "binary_sensor", key).state == value, key

    tracker = state(hass, "device_tracker", "location")
    assert tracker.attributes["latitude"] == 52.0907
    assert tracker.attributes["longitude"] == 5.1214

    assert state(hass, "lock", "lock_doors").state == "locked"
    assert state(hass, "switch", "switch_precondition").state == "off"
    assert state(hass, "switch", "switch_charging").state == "on"


@pytest.mark.parametrize(
    ("enrolled", "command_entities", "buttons"),
    [(False, True, {"update"}), (True, False, None), (False, False, None)],
)
async def test_command_entities_need_setup_and_option(
    hass: HomeAssistant,
    ssdp_client: FakeSsdpClientFactory,
    enrolled: bool,
    command_entities: bool,
    buttons: set[str] | None,
) -> None:
    entry = make_ssdp_entry(enrolled=enrolled, command_entities=command_entities)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entities = registered(hass, entry)
    assert Platform.LOCK not in entities
    assert Platform.SWITCH not in entities
    assert entities.get(Platform.BUTTON) == buttons

    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("platform", "service", "key", "command"),
    [
        ("lock", "lock", "lock_doors", remote.lock_doors()),
        ("lock", "unlock", "lock_doors", remote.unlock_doors()),
        ("switch", "turn_on", "switch_engine", remote.engine(True)),
        ("switch", "turn_off", "switch_engine", remote.engine(False)),
        ("switch", "turn_on", "switch_precondition", remote.preconditioning(True)),
        ("switch", "turn_off", "switch_precondition", remote.preconditioning(False)),
        ("switch", "turn_on", "switch_charging", remote.charge_now(True)),
        ("switch", "turn_off", "switch_charging", remote.charge_now(False)),
        ("button", "press", "button_horn", remote.horn()),
        ("button", "press", "button_lights", remote.lights()),
        ("button", "press", "button_deep_refresh", remote.wakeup()),
        ("button", "press", "button_location", remote.locate()),
    ],
)
async def test_commands(
    hass: HomeAssistant,
    setup_ssdp_integration: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
    platform: str,
    service: str,
    key: str,
    command: remote.RemoteCommand,
) -> None:
    client = ssdp_client.last
    refreshes = client.refresh.await_count

    await hass.services.async_call(
        platform, service, {"entity_id": entity_id(hass, platform, key)}, blocking=True
    )
    await hass.async_block_till_done()

    client.command_verify.assert_awaited_once_with(SSDP_VIN, command)
    assert client.refresh.await_count > refreshes


async def test_update_button(
    hass: HomeAssistant,
    setup_ssdp_integration: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
) -> None:
    client = ssdp_client.last
    refreshes = client.refresh.await_count

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": entity_id(hass, "button", "update")},
        blocking=True,
    )

    assert client.refresh.await_count == refreshes + 1
    client.command_verify.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "raised", "message"),
    [
        (RemoteAuthenticationError("PIN"), HomeAssistantError, "not authorized"),
        (CommandTimeoutError("slow"), UconnectCommandTimeout, "in time"),
        (CommandError("DoorsOpen"), HomeAssistantError, "DoorsOpen"),
        (SSDPConnectionError("down"), HomeAssistantError, "down"),
    ],
)
async def test_command_errors(
    hass: HomeAssistant,
    setup_ssdp_integration: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
    error: Exception,
    raised: type[Exception],
    message: str,
) -> None:
    ssdp_client.last.command_verify.side_effect = error

    with pytest.raises(raised, match=message):
        await hass.services.async_call(
            "lock",
            "lock",
            {"entity_id": entity_id(hass, "lock", "lock_doors")},
            blocking=True,
        )


# --- Coordinator ---------------------------------------------------------------------


async def test_state_is_saved(
    hass: HomeAssistant,
    setup_ssdp_integration: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
) -> None:
    client = ssdp_client.last
    assert client.kwargs["email"] == "user@example.com"
    assert client.kwargs["password"] == "secret"
    assert client.kwargs["pin"] == "1234"
    assert client.brand is stellantis_ssdp.JEEP_EU

    new = make_ssdp_state()
    new.token = make_ssdp_token("RENEWED")
    client.kwargs["on_state_change"](new)

    saved = setup_ssdp_integration.data[CONF_SSDP_STATE]
    assert saved["token"]["access_token"] == "RENEWED"
    assert State.from_dict(saved).token.user_id == SSDP_USER_ID


async def test_auth_error_after_setup_starts_reauth(
    hass: HomeAssistant,
    setup_ssdp_integration: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
) -> None:
    ssdp_client.last.refresh.side_effect = AuthenticationError("password changed")

    await setup_ssdp_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"]["source"] == "reauth"


async def test_errors_after_setup_keep_data(
    hass: HomeAssistant,
    setup_ssdp_integration: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
) -> None:
    ssdp_client.last.refresh.side_effect = SSDPConnectionError("down")

    coordinator = setup_ssdp_integration.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success
    assert state(hass, "sensor", "state_of_charge").state == "49"
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_no_vehicles_warning(
    hass: HomeAssistant,
    ssdp_config_entry: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ssdp_client.list_items = []

    assert await hass.config_entries.async_setup(ssdp_config_entry.entry_id)
    await hass.async_block_till_done()

    assert "No vehicles found in the JEEP_EU_SSDP account" in caplog.text
    await hass.config_entries.async_unload(ssdp_config_entry.entry_id)


# --- Several entries ---------------------------------------------------------------


async def test_with_uconnect_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: FakeClient,
    ssdp_config_entry: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
) -> None:
    # Sets up all the entries of the integration
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert ssdp_config_entry.state is ConfigEntryState.LOADED

    # async_get_coordinators stays for the Uconnect entries
    assert [c.config_entry for c in async_get_coordinators(hass)] == [config_entry]
    assert hass.services.has_service(DOMAIN, "doors_lock")
    assert hass.services.has_service(DOMAIN, "lights_horn")
    assert hass.services.has_service(DOMAIN, "horn")

    # The vehicle card lists the vehicles of both entries
    vehicles = {v["vin"]: v for v in _build_vehicle_list(hass)}
    assert set(vehicles) == {EV_VIN, ICE_VIN, SSDP_VIN}
    assert vehicles[SSDP_VIN]["name"] == "JEEP Compass"
    assert {"soc", "range", "odometer", "device_tracker", "fuel"} <= set(
        vehicles[SSDP_VIN]["entities"]
    )

    with patch(
        "custom_components.uconnect.async_unload_frontend_cards_if_last_entry"
    ) as unload_cards:
        # Unloading the Uconnect entry keeps the card and the actions of the
        # SSDP vehicle, the Uconnect-only actions are removed
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
        assert hass.services.has_service(DOMAIN, "doors_lock")
        assert hass.services.has_service(DOMAIN, "horn")
        assert not hass.services.has_service(DOMAIN, "lights_horn")
        unload_cards.assert_not_awaited()

        await hass.config_entries.async_unload(ssdp_config_entry.entry_id)
        await hass.async_block_till_done()
        assert not hass.services.async_services_for_domain(DOMAIN)
        unload_cards.assert_awaited_once()


async def test_same_vehicle_in_two_entries(
    hass: HomeAssistant,
    ssdp_client: FakeSsdpClientFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One Stellantis account set up with two brands lists the same vehicle"""

    first = make_ssdp_entry(brand=21)
    second = make_ssdp_entry(brand=22)
    for entry in (first, second):
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert first.runtime_data.vehicles.keys() == {SSDP_VIN}
    assert second.runtime_data.vehicles == {}
    assert registered(hass, first)[Platform.SENSOR] == SENSORS
    assert registered(hass, second) == {}
    assert "already provided by another entry" in caplog.text
    assert "does not generate unique IDs" not in caplog.text

    # Later refreshes keep it so, and warn only once
    caplog.clear()
    await second.runtime_data.async_refresh()
    await first.runtime_data.async_refresh()
    assert first.runtime_data.vehicles.keys() == {SSDP_VIN}
    assert second.runtime_data.vehicles == {}
    assert "already provided" not in caplog.text

    for entry in (first, second):
        await hass.config_entries.async_unload(entry.entry_id)


async def test_same_vehicle_entry_with_larger_id_loaded_first(
    hass: HomeAssistant, ssdp_client: FakeSsdpClientFactory
) -> None:
    """The entry that shows a vehicle keeps it, whatever the order the entries
    are loaded in"""

    low, high = sorted(
        (make_ssdp_entry(brand=21), make_ssdp_entry(brand=22)),
        key=lambda e: e.entry_id,
    )

    for entry in (high, low):
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert high.runtime_data.vehicles.keys() == {SSDP_VIN}
    assert low.runtime_data.vehicles == {}

    for entry in (low, high):
        await hass.config_entries.async_unload(entry.entry_id)


async def test_brand_of_entry(
    hass: HomeAssistant, ssdp_client: FakeSsdpClientFactory
) -> None:
    entry = make_ssdp_entry(brand=24)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert ssdp_client.last.brand is stellantis_ssdp.OPEL_EU
    assert entry.data[CONF_BRAND_REGION] == 24
    await hass.config_entries.async_unload(entry.entry_id)


# --- Actions ---------------------------------------------------------------------------

SSDP_ACTIONS = {
    "update",
    "engine_on",
    "engine_off",
    "precond_on",
    "precond_off",
    "lights",
    "horn",
    "doors_lock",
    "doors_unlock",
    "charge_now",
    "deep_refresh",
    "refresh_location",
    "send_destination",
}


def ssdp_device_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return device.id


async def test_actions_registered(
    hass: HomeAssistant, setup_ssdp_integration: MockConfigEntry
) -> None:
    assert set(hass.services.async_services_for_domain(DOMAIN)) == SSDP_ACTIONS


async def test_actions_need_remote_commands(
    hass: HomeAssistant, ssdp_client: FakeSsdpClientFactory
) -> None:
    entry = make_ssdp_entry(enrolled=False)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert set(hass.services.async_services_for_domain(DOMAIN)) == {"update"}

    await hass.config_entries.async_unload(entry.entry_id)


async def test_charge_now_needs_battery(
    hass: HomeAssistant,
    ssdp_config_entry: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
) -> None:
    telemetry = ssdp_client.telemetry[SSDP_VIN]
    telemetry["vehicle"]["energies"] = [
        e for e in telemetry["vehicle"]["energies"] if e["type"] != "Electric"
    ]

    assert await hass.config_entries.async_setup(ssdp_config_entry.entry_id)
    await hass.async_block_till_done()

    actions = set(hass.services.async_services_for_domain(DOMAIN))
    assert actions == SSDP_ACTIONS - {"charge_now"}

    await hass.config_entries.async_unload(ssdp_config_entry.entry_id)


@pytest.mark.parametrize(
    ("action", "data", "command"),
    [
        ("engine_on", {}, remote.engine(True)),
        ("engine_off", {}, remote.engine(False)),
        ("precond_on", {}, remote.preconditioning(True)),
        ("precond_off", {}, remote.preconditioning(False)),
        ("lights", {}, remote.lights()),
        ("horn", {}, remote.horn()),
        ("doors_lock", {}, remote.lock_doors()),
        ("doors_unlock", {}, remote.unlock_doors()),
        ("charge_now", {}, remote.charge_now(True)),
        ("deep_refresh", {}, remote.wakeup()),
        ("refresh_location", {}, remote.locate()),
        (
            "send_destination",
            {"latitude": 52.1, "longitude": 5.2},
            remote.send_destination(52.1, 5.2),
        ),
        (
            "send_destination",
            {"latitude": 52.1, "longitude": 5.2, "name": "Home"},
            remote.send_destination(52.1, 5.2, "Home"),
        ),
    ],
)
async def test_actions(
    hass: HomeAssistant,
    setup_ssdp_integration: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
    action: str,
    data: dict[str, Any],
    command: remote.RemoteCommand,
) -> None:
    # With a single vehicle the device can be omitted
    await hass.services.async_call(DOMAIN, action, data, blocking=True)

    ssdp_client.last.command_verify.assert_awaited_once_with(SSDP_VIN, command)


async def test_update_action(
    hass: HomeAssistant,
    setup_ssdp_integration: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
) -> None:
    refreshes = ssdp_client.last.refresh.await_count

    await hass.services.async_call(
        DOMAIN,
        "update",
        {"device_id": ssdp_device_id(hass, setup_ssdp_integration)},
        blocking=True,
    )

    assert ssdp_client.last.refresh.await_count == refreshes + 1
    ssdp_client.last.command_verify.assert_not_awaited()


async def test_actions_with_uconnect_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: FakeClient,
    ssdp_config_entry: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    ssdp_device = ssdp_device_id(hass, ssdp_config_entry)
    uconnect_device = next(
        d.id
        for d in dr.async_entries_for_config_entry(
            dr.async_get(hass), config_entry.entry_id
        )
        if (DOMAIN, ICE_VIN) in d.identifiers
    )

    # The same action runs the command of the backend of the vehicle
    await hass.services.async_call(
        DOMAIN, "doors_lock", {"device_id": ssdp_device}, blocking=True
    )
    ssdp_client.last.command_verify.assert_awaited_once_with(
        SSDP_VIN, remote.lock_doors()
    )
    fake_client.command_verify.assert_not_awaited()

    await hass.services.async_call(
        DOMAIN, "doors_lock", {"device_id": uconnect_device}, blocking=True
    )
    assert fake_client.command_verify.await_args.args[:2] == (
        ICE_VIN,
        COMMAND_DOORS_LOCK,
    )

    # Uconnect-only actions are not supported by the SSDP vehicle, and the
    # SSDP-only ones not by the Uconnect vehicles
    with pytest.raises(ServiceValidationError, match="not supported"):
        await hass.services.async_call(
            DOMAIN, "lights_horn", {"device_id": ssdp_device}, blocking=True
        )
    with pytest.raises(ServiceValidationError, match="not supported"):
        await hass.services.async_call(
            DOMAIN, "horn", {"device_id": uconnect_device}, blocking=True
        )

    # Several vehicles: the device has to be given
    with pytest.raises(ServiceValidationError, match="must be selected"):
        await hass.services.async_call(DOMAIN, "horn", {}, blocking=True)

    for entry in (config_entry, ssdp_config_entry):
        await hass.config_entries.async_unload(entry.entry_id)


# --- Review fixes ------------------------------------------------------------------------


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_data_updates_do_not_reload(
    hass: HomeAssistant, ssdp_client: FakeSsdpClientFactory
) -> None:
    """Saving the state, also while remote commands are being set up, does not
    reload the entry"""

    entry = make_ssdp_entry(enrolled=False)
    await setup_entry(hass, entry)
    client = ssdp_client.last

    # The soft token is activated, the setup is not finished yet
    client.state.soft_token = make_ssdp_state().soft_token
    client.kwargs["on_state_change"](client.state)
    await hass.async_block_till_done()

    assert len(ssdp_client.instances) == 1
    assert entry.state is ConfigEntryState.LOADED
    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_set_up_remote_commands_unchanged_options(
    hass: HomeAssistant, ssdp_client: FakeSsdpClientFactory
) -> None:
    """With the options already as the setup leaves them, the entry is
    reloaded once, after the final state is saved"""

    entry = make_ssdp_entry(enrolled=False)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_PIN: "1234"}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = ssdp_client.last

    async def enroll_finish(code: str, pin: str) -> None:
        save = client.kwargs["on_state_change"]
        # Like the library: the soft token is saved after its activation...
        client.state.soft_token = make_ssdp_state().soft_token
        save(client.state)
        await asyncio.sleep(0)
        # ...and again after the one-time password rotated its key
        client.state.soft_token.k1 = "9" * 32
        client.state.remote_token = make_ssdp_token("RCZ-FINAL")
        save(client.state)

    client.enroll_finish.side_effect = enroll_finish

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "ssdp_send_sms"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"sms_code": "123456", "pin": "1234"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # Reloaded once, with the final state
    assert len(ssdp_client.instances) == 2
    reloaded = ssdp_client.last.state
    assert reloaded.soft_token is not None
    assert reloaded.soft_token.k1 == "9" * 32
    assert reloaded.remote_token is not None
    assert reloaded.remote_token.access_token == "RCZ-FINAL"
    assert Platform.LOCK in registered(hass, entry)

    await hass.config_entries.async_unload(entry.entry_id)


async def test_update_button_follows_option_without_remote_commands(
    hass: HomeAssistant, ssdp_client: FakeSsdpClientFactory
) -> None:
    entry = make_ssdp_entry(enrolled=False, command_entities=False)
    await setup_entry(hass, entry)

    async def set_option(value: bool) -> None:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "ssdp_settings"}
        )
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"scan_interval": 5, "pin": "", CONF_ADD_COMMAND_ENTITIES: value},
        )
        await hass.async_block_till_done()

    await set_option(True)
    assert len(ssdp_client.instances) == 2
    button = hass.states.get(entity_id(hass, "button", "update"))
    assert button is not None and button.state != "unavailable"

    await set_option(False)
    assert len(ssdp_client.instances) == 3
    button = hass.states.get(entity_id(hass, "button", "update"))
    assert button is None or button.state == "unavailable"

    await hass.config_entries.async_unload(entry.entry_id)


async def test_login_follows_tls_option(hass: HomeAssistant, login: AsyncMock) -> None:
    session = MagicMock()
    create = MagicMock(return_value=session)

    with patch(
        "custom_components.uconnect.config_flow.async_create_login_session", create
    ):
        await start_flow(hass, {**USER_INPUT, "disable_tls_verification": True})

    create.assert_called_once_with(hass, False, auto_cleanup=False)
    assert login.call_args.kwargs["session"] is session
    session.detach.assert_called_once()


async def test_client_login_session_follows_tls_option(
    hass: HomeAssistant, ssdp_client: FakeSsdpClientFactory
) -> None:
    entry = make_ssdp_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "disable_tls_verification": True}
    )
    create = MagicMock(return_value=MagicMock())

    with patch(
        "custom_components.uconnect.ssdp.coordinator.async_create_login_session",
        create,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    create.assert_called_once_with(hass, False)
    assert ssdp_client.last.kwargs["login_session"] is create.return_value
    await hass.config_entries.async_unload(entry.entry_id)


async def test_action_without_device_two_entries_one_vehicle(
    hass: HomeAssistant, ssdp_client: FakeSsdpClientFactory
) -> None:
    first = make_ssdp_entry(brand=21)
    second = make_ssdp_entry(brand=22)
    for entry in (first, second):
        await setup_entry(hass, entry)

    await hass.services.async_call(DOMAIN, "horn", {}, blocking=True)

    owner = next(e for e in (first, second) if e.runtime_data.vehicles)
    owner.runtime_data.client.command_verify.assert_awaited_once_with(
        SSDP_VIN, remote.horn()
    )

    for entry in (first, second):
        await hass.config_entries.async_unload(entry.entry_id)


async def test_owner_reload_keeps_vehicle(
    hass: HomeAssistant, ssdp_client: FakeSsdpClientFactory
) -> None:
    low, high = sorted(
        (make_ssdp_entry(brand=21), make_ssdp_entry(brand=22)),
        key=lambda e: e.entry_id,
    )
    for entry in (high, low):
        await setup_entry(hass, entry)
    assert high.runtime_data.vehicles.keys() == {SSDP_VIN}

    # Reloading the entry with the larger ID keeps the vehicle with it
    assert await hass.config_entries.async_reload(high.entry_id)
    await hass.async_block_till_done()
    await low.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert high.runtime_data.vehicles.keys() == {SSDP_VIN}
    assert low.runtime_data.vehicles == {}
    assert registered(hass, high)[Platform.SENSOR] == SENSORS

    for entry in (low, high):
        await hass.config_entries.async_unload(entry.entry_id)


async def test_vehicle_handed_over_when_owner_unloaded(
    hass: HomeAssistant, ssdp_client: FakeSsdpClientFactory
) -> None:
    first = make_ssdp_entry(brand=21)
    second = make_ssdp_entry(brand=22)
    for entry in (first, second):
        await setup_entry(hass, entry)
    assert second.runtime_data.vehicles == {}

    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()
    await second.runtime_data.async_refresh()
    await hass.async_block_till_done()

    # The second entry was reloaded and provides the vehicle with its entities
    assert second.state is ConfigEntryState.LOADED
    assert second.runtime_data.vehicles.keys() == {SSDP_VIN}
    assert registered(hass, second)[Platform.SENSOR] == SENSORS
    assert state(hass, "sensor", "state_of_charge").state == "49"

    await hass.config_entries.async_unload(second.entry_id)


async def test_uconnect_entry_takes_over_vehicle(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: FakeClient,
    ssdp_client: FakeSsdpClientFactory,
) -> None:
    """A vehicle also in a Uconnect account goes to the Uconnect entry, also
    when the SSDP entry provided it first"""

    ssdp_client.list_items = [{**ssdp_client.list_items[0], "vin": EV_VIN}]
    ssdp_client.telemetry = {EV_VIN: ssdp_client.telemetry[SSDP_VIN]}
    # The Uconnect entry is added after the SSDP one
    await hass.config_entries.async_remove(config_entry.entry_id)

    ssdp_entry = make_ssdp_entry()
    await setup_entry(hass, ssdp_entry)
    assert ssdp_entry.runtime_data.vehicles.keys() == {EV_VIN}

    uconnect_entry = MockConfigEntry(
        domain=DOMAIN,
        title=config_entry.title,
        unique_id=config_entry.unique_id,
        data=dict(config_entry.data),
        options=dict(config_entry.options),
    )
    await setup_entry(hass, uconnect_entry)

    await ssdp_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    # The SSDP entry gave the vehicle up, the Uconnect entry was reloaded and
    # has its entities
    assert ssdp_entry.runtime_data.vehicles == {}
    reg = er.async_get(hass)
    owners = {
        e.config_entry_id
        for e in reg.entities.values()
        if e.unique_id.startswith(f"{DOMAIN}_{EV_VIN}_")
        and hass.states.get(e.entity_id) is not None
        and hass.states.get(e.entity_id).state != "unavailable"
    }
    assert owners == {uconnect_entry.entry_id}
    odometer = reg.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{EV_VIN}_odometer")
    assert odometer is not None
    assert reg.async_get(odometer).config_entry_id == uconnect_entry.entry_id

    for entry in (ssdp_entry, uconnect_entry):
        await hass.config_entries.async_unload(entry.entry_id)
