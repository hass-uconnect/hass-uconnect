"""Setup, unload and entity creation."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from py_uconnect import AuthenticationError, UconnectConnectionError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.uconnect.const import DOMAIN

from .conftest import EV_VIN, ICE_VIN, FakeClient

# Entities created by the integration before py-uconnect 1.0 for the fixture
# data, per platform. Their unique IDs must not change.
OLD_ENTITIES: dict[str, dict[str, set[str]]] = {
    EV_VIN: {
        "binary_sensor": {
            "ignition_on",
            "ev_running",
            "door_driver_locked",
            "door_passenger_locked",
            "door_rear_left_locked",
            # Reported as NA: was "unlocked", unknown now
            "door_rear_right_locked",
            "trunk_locked",
            "window_driver_closed",
            "window_passenger_closed",
            "plugged_in",
            "charging",
            "wheel_front_left_pressure_warning",
            "wheel_front_right_pressure_warning",
            "wheel_rear_left_pressure_warning",
            "wheel_rear_right_pressure_warning",
            "ev_head_seat",
            "ev_cabin_cond",
            "svla",
        },
        "sensor": {
            "odometer",
            "distance_to_empty",
            "range_total",
            "state_of_charge",
            "charging_level",
            "battery_voltage",
            "time_to_fully_charge_l2",
            "time_to_fully_charge_l3",
            "distance_to_service",
            "days_to_service",
            "wheel_front_left_pressure",
            "wheel_front_right_pressure",
            "wheel_rear_left_pressure",
            "timestamp_info",
            "timestamp_status",
            "last_location_update",
            "fuel_type",
            "battery_state_of_charge",
            "vhr",
            "maintenance",
            "charge_schedule",
            "extrapolated_soc",
            "charging_rate",
        },
        "device_tracker": {"location"},
        "image": {"image"},
        "lock": {"lock_doors"},
        "switch": {"switch_precondition", "switch_trunk"},
        "button": {
            "update",
            "button_location",
            "button_lights",
            "reset_battery_learning",
        },
        "select": {"charging_level_preference"},
    },
    ICE_VIN: {
        "binary_sensor": {
            "ignition_on",
            "wheel_front_left_pressure_warning",
            "wheel_front_right_pressure_warning",
            "wheel_rear_left_pressure_warning",
            "wheel_rear_right_pressure_warning",
            "fuel_low",
            "svla",
        },
        "sensor": {
            "odometer",
            "distance_to_empty",
            "battery_voltage",
            "distance_to_service",
            "wheel_front_left_pressure",
            "wheel_front_right_pressure",
            "wheel_rear_left_pressure",
            "wheel_rear_right_pressure",
            "oil_level",
            "fuel_amount",
            "timestamp_info",
            "last_location_update",
            "fuel_type",
            "battery_state_of_charge",
            "vhr",
            "maintenance",
        },
        "device_tracker": {"location"},
        "image": {"image"},
        "lock": {"lock_doors"},
        "switch": {"switch_engine"},
        "button": {"update", "button_location", "button_lights_horn"},
    },
}

# Entities added by this version for the fixture data
NEW_ENTITIES: dict[str, dict[str, set[str]]] = {
    EV_VIN: {
        "binary_sensor": {
            "window_rear_left_closed",
            "window_rear_right_closed",
            "liftgate_locked",
            "hvac_on",
        },
        "sensor": {"hvac_temperature", "privacy_mode"},
        # The vehicle has CNOW2 and DEEPREFRESH2, which now enable these
        "switch": {"switch_charging"},
        "button": {"button_charge", "button_deep_refresh"},
    },
}


def unique_ids(entities: dict[str, dict[str, set[str]]]) -> set[tuple[str, str]]:
    return {
        (platform, f"{DOMAIN}_{vin}_{key}")
        for vin, platforms in entities.items()
        for platform, keys in platforms.items()
        for key in keys
    }


def registered(hass: HomeAssistant, entry: MockConfigEntry) -> set[tuple[str, str]]:
    return {
        (e.domain, e.unique_id)
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


async def test_setup_fresh_install(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    assert setup_integration.state is ConfigEntryState.LOADED

    expected = unique_ids(OLD_ENTITIES) | unique_ids(NEW_ENTITIES)
    # A fresh install doesn't get the entity for the door reported as NA
    expected.remove(("binary_sensor", f"{DOMAIN}_{EV_VIN}_door_rear_right_locked"))

    assert registered(hass, setup_integration) == expected

    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), setup_integration.entry_id
    )
    assert {d.name for d in devices} == {"FIAT 500", "JEEP Wrangler"}


async def test_existing_entities_are_kept(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    """Every entity created by previous versions is still provided"""

    registry = er.async_get(hass)
    for platform, unique_id in unique_ids(OLD_ENTITIES):
        registry.async_get_or_create(
            platform, DOMAIN, unique_id, config_entry=config_entry
        )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    for platform, unique_id in unique_ids(OLD_ENTITIES):
        entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
        state = hass.states.get(entity_id)
        assert state is not None, unique_id
        assert state.state != STATE_UNAVAILABLE, unique_id

    door = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{DOMAIN}_{EV_VIN}_door_rear_right_locked"
    )
    assert hass.states.get(door).state == STATE_UNKNOWN

    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_command_entities_disabled(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, "add_command_entities": False}
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    platforms = {p for p, _ in registered(hass, config_entry)}
    assert not platforms & {"lock", "switch", "select"}
    buttons = {u for p, u in registered(hass, config_entry) if p == "button"}
    assert buttons == {f"{DOMAIN}_{EV_VIN}_reset_battery_learning"}

    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_unload(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    assert hass.services.has_service(DOMAIN, "update")

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.async_services_for_domain(DOMAIN)


async def test_client_is_configured(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    kwargs = fake_client.init_kwargs
    assert kwargs["email"] == "user@example.com"
    assert kwargs["password"] == "secret"
    # The option is empty, the PIN from the setup applies
    assert kwargs["pin"] == "1234"
    assert kwargs["brand"].name == "FIAT_EU"
    assert kwargs["session"] is not None


async def test_setup_auth_failure_starts_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.refresh.side_effect = AuthenticationError("Invalid LoginID")

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_setup_connection_failure_retries(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.refresh.side_effect = UconnectConnectionError("timeout")

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_vehicle_removed_from_account(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{DOMAIN}_{ICE_VIN}_odometer"
    )
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE

    fake_client.list_items = [x for x in fake_client.list_items if x["vin"] != ICE_VIN]
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_two_entries(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    other = MockConfigEntry(
        domain=DOMAIN,
        title="JEEP_US other@example.com",
        unique_id="fedcba9876543210",
        data={**setup_integration.data, "username": "other@example.com"},
        options=setup_integration.options,
    )
    other.add_to_hass(hass)
    fake_client.list_items = []

    assert await hass.config_entries.async_setup(other.entry_id)
    await hass.async_block_till_done()

    # Unloading one entry keeps the actions of the other
    assert await hass.config_entries.async_unload(other.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, "update")
