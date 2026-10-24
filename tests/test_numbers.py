"""Numbers are shown like with py-uconnect 0.x."""

from __future__ import annotations

import math

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.uconnect.const import DOMAIN
from custom_components.uconnect.coordinator import whole_to_int
from custom_components.uconnect.extrapolated_soc import SocEstimationState

from .conftest import EV_VIN, ICE_VIN, FakeClient


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (63.0, 63),
        (0.0, 0),
        (-1.0, -1),
        (63.5, 63.5),
        (63, 63),
        (True, True),
        ("63", "63"),
        (None, None),
        (math.inf, math.inf),
    ],
)
def test_whole_to_int(value: object, expected: object) -> None:
    result = whole_to_int(value)

    assert result == expected
    assert type(result) is type(expected)


def test_whole_to_int_nan() -> None:
    assert math.isnan(whole_to_int(math.nan))


def test_restored_soc_is_int() -> None:
    """State saved by 1.0.0 had floats, shown with a decimal until a change"""

    state = SocEstimationState.from_dict(
        {"last_actual_soc": 63.0, "last_vehicle_soc": 63.0}
    )

    assert type(state.last_actual_soc) is int
    assert type(state.last_vehicle_soc) is int

    state = SocEstimationState.from_dict({"last_actual_soc": 63.4})
    assert state.last_actual_soc == 63.4


def sensor_state(hass: HomeAssistant, vin: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{DOMAIN}_{vin}_{key}"
    )
    assert entity_id is not None, key
    return hass.states.get(entity_id).state


async def test_sensor_states(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    # Whole numbers are integers, as the API sends them ("63", not "63.0")
    assert sensor_state(hass, EV_VIN, "state_of_charge") == "63"
    assert sensor_state(hass, EV_VIN, "odometer") == "1841"
    assert sensor_state(hass, EV_VIN, "distance_to_empty") == "134"
    assert sensor_state(hass, EV_VIN, "range_total") == "134"
    assert sensor_state(hass, EV_VIN, "wheel_front_left_pressure") == "250"
    assert sensor_state(hass, EV_VIN, "days_to_service") == "325"
    assert sensor_state(hass, EV_VIN, "time_to_fully_charge_l2") == "96"

    # Decimals are kept
    assert sensor_state(hass, EV_VIN, "battery_voltage") == "14.875"
    assert sensor_state(hass, ICE_VIN, "fuel_amount") == "52.5"

    vehicle = fake_client.vehicles[EV_VIN]
    assert type(vehicle.state_of_charge) is int
    assert vehicle.location is not None
    assert type(vehicle.location.bearing) is int
    assert type(vehicle.location.latitude) is float


async def test_extrapolated_soc_without_extrapolation(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    """Not charging with the ignition on, the vehicle's value is shown as is"""

    ev = fake_client.info[EV_VIN]["evInfo"]
    ev["battery"]["chargingStatus"] = "IDLE"
    ev["ignitionStatus"] = "ON"
    fake_client.remote[EV_VIN]["engine"]["status"] = "ON"

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert sensor_state(hass, EV_VIN, "extrapolated_soc") == "63"

    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_driving_range_with_zero_battery_range(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    """Vehicles with a combustion engine (or a PHEV with an empty battery)
    report a battery range of 0, the driving range is the fuel range then"""

    fake_client.info[ICE_VIN]["evInfo"]["battery"] = {
        "distanceToEmpty": {"unit": "mi", "value": "0"}
    }

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # 410 mi, converted to km by the metric test instance
    assert round(float(sensor_state(hass, ICE_VIN, "distance_to_empty"))) == 660

    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_svla_activation_timestamp_is_local(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.api.get_stolen_vehicle_status.return_value = {
        "svlaStatus": True,
        "activationTimestamp": 1738660203634,
    }

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{DOMAIN}_{EV_VIN}_svla"
    )
    activation = hass.states.get(entity_id).attributes["activation_timestamp"]

    assert activation == dt_util.utc_from_timestamp(1738660203.634)
    assert activation.tzinfo == dt_util.get_default_time_zone()

    await hass.config_entries.async_unload(config_entry.entry_id)
