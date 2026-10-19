"""Fixtures for the Uconnect integration tests.

The py-uconnect client is replaced by FakeClient, which builds real Vehicle
objects from JSON fixtures with the library's own parsers, so entities see the
same data as with the real client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
import copy
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import (
    CONF_PASSWORD,
    CONF_PIN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from py_uconnect import APIError, Vehicle
from py_uconnect.models import (
    apply_list_item,
    apply_remote_status,
    apply_vehicle_info,
    parse_location,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.uconnect.const import (
    CONF_ADD_COMMAND_ENTITIES,
    CONF_BRAND_REGION,
    CONF_CHARGING_REFRESH_INTERVAL,
    CONF_DISABLE_TLS_VERIFICATION,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"

EV_VIN = "ZFAEFAC39MX000001"
ICE_VIN = "1C4HJXEN5MW000002"
IMAGE_URL = "https://example.com/vehicle/jeep.png"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


class FakeClient:
    """Stand-in for py_uconnect.Client"""

    def __init__(self) -> None:
        self.vehicles: dict[str, Vehicle] = {}
        self.init_kwargs: dict[str, Any] = {}

        # API responses used by refresh(), per VIN. Missing ones fail like an
        # unsupported endpoint does.
        self.list_items: list[dict[str, Any]] = load_fixture("vehicles.json")[
            "vehicles"
        ]
        self.info: dict[str, dict] = {
            EV_VIN: load_fixture("status_ev.json"),
            ICE_VIN: load_fixture("status_ice.json"),
        }
        self.remote: dict[str, dict] = {EV_VIN: load_fixture("remote_status.json")}
        self.location: dict[str, dict] = {
            EV_VIN: load_fixture("location.json"),
            ICE_VIN: load_fixture("location.json"),
        }

        self.refresh = AsyncMock(side_effect=self._refresh)
        self.command_verify = AsyncMock(return_value=True)
        self.set_charging_level_verify = AsyncMock(return_value=True)
        self.set_charge_schedules_verify = AsyncMock(return_value=True)
        self.wait_for_operation = AsyncMock(return_value=True)

        self.api = MagicMock()
        self.api.pin = None
        self.api.get_vehicle_health_report = AsyncMock(
            return_value={
                "reportCard": {
                    "timestamp": 1738660203634,
                    "items": [
                        {
                            "itemKey": "engine",
                            "value": "OK",
                            "items": [{"itemKey": "oil", "value": "OK"}],
                        }
                    ],
                }
            }
        )
        self.api.get_maintenance_history = AsyncMock(
            return_value={
                "serviceHistory": [
                    {
                        "date": 1700000000000,
                        "description": "Annual service",
                        "dealer": "Dealer",
                        "odometer": 15000,
                        "location": "Turin",
                    }
                ]
            }
        )
        self.api.get_stolen_vehicle_status = AsyncMock(
            return_value={"svlaStatus": False, "activationTimestamp": 0}
        )
        self.api.get_vehicle_image = AsyncMock(
            return_value={"items": [{"id": ICE_VIN, "preciseImageURL": IMAGE_URL}]}
        )
        self.api.send_destination = AsyncMock(return_value="CID")

    def __call__(self, **kwargs: Any) -> FakeClient:
        """Used as the Client class: returns itself"""

        self.init_kwargs = kwargs
        self.api.pin = kwargs.get("pin")
        return self

    async def _refresh(self) -> dict[str, Vehicle]:
        vins = set()

        for item in copy.deepcopy(self.list_items):
            vin = item["vin"]
            vins.add(vin)
            v = self.vehicles.get(vin) or Vehicle(vin=vin)
            apply_list_item(v, item)

            if vin in self.info:
                apply_vehicle_info(v, copy.deepcopy(self.info[vin]))
            if vin in self.location:
                v.location = parse_location(self.location[vin])
            if vin in self.remote:
                apply_remote_status(v, copy.deepcopy(self.remote[vin]))

            self.vehicles[vin] = v

        for vin in set(self.vehicles) - vins:
            del self.vehicles[vin]

        return self.vehicles

    def get_vehicles(self) -> dict[str, Vehicle]:
        return self.vehicles

    def set_pin(self, pin: str | None) -> None:
        self.api.pin = pin

    def add_services(self, vin: str, *services: str) -> None:
        """Enable additional services for a vehicle"""

        item = next(x for x in self.list_items if x["vin"] == vin)
        item["services"] += [
            {"service": s, "serviceEnabled": True, "vehicleCapable": True}
            for s in services
        ]


def not_found() -> APIError:
    return APIError("not found", status=404)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading the custom integration in all tests"""


@pytest.fixture
def fake_client() -> Iterator[FakeClient]:
    client = FakeClient()
    with patch("custom_components.uconnect.coordinator.Client", client):
        yield client


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="FIAT_EU user@example.com",
        unique_id="0123456789abcdef",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
            CONF_BRAND_REGION: 1,
            CONF_PIN: "1234",
            CONF_DISABLE_TLS_VERIFICATION: False,
        },
        options={
            CONF_SCAN_INTERVAL: 5,
            CONF_PIN: "",
            CONF_CHARGING_REFRESH_INTERVAL: 30,
            CONF_ADD_COMMAND_ENTITIES: True,
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> AsyncIterator[MockConfigEntry]:
    """Set up the integration and unload it after the test"""

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    yield config_entry

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
