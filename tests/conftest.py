"""Fixtures for the Uconnect integration tests.

The py-uconnect client is replaced by FakeClient, which builds real Vehicle
objects from JSON fixtures with the library's own parsers, so entities see the
same data as with the real client.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Iterator
import copy
from datetime import UTC, datetime, timedelta
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
from stellantis_ssdp import SoftTokenState, State, Token, Vehicle as SsdpVehicle
from stellantis_ssdp.models import (
    apply_list_item as apply_ssdp_list_item,
    apply_telemetry,
)

from custom_components.uconnect.config_flow import entry_unique_id
from custom_components.uconnect.const import (
    BRANDS,
    CONF_ADD_COMMAND_ENTITIES,
    CONF_BRAND_REGION,
    CONF_CHARGING_REFRESH_INTERVAL,
    CONF_DISABLE_TLS_VERIFICATION,
    CONF_SSDP_STATE,
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
        unique_id=entry_unique_id(1, "user@example.com"),
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


# --- SSDP brands ---------------------------------------------------------------

SSDP_VIN = "ZACNJDE00SPA00001"
SSDP_USER_ID = "ssdp-user-1"
SSDP_BRAND = 21


def make_jwt(claims: dict[str, Any]) -> str:
    def enc(d: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


def make_ssdp_token(access: str = "ACCESS", sub: str = SSDP_USER_ID) -> Token:
    return Token(
        access_token=access,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        refresh_token="REFRESH",
        id_token=make_jwt({"sub": sub}),
    )


def enrolled_soft_token() -> SoftTokenState:
    return SoftTokenState(
        device_id="dev",
        alea="00" * 16,
        id="IW-ID",
        k1="1" * 32,
        services=["svc"],
        secrets={"svc": "2" * 32},
    )


def make_ssdp_state(enrolled: bool = True) -> State:
    return State(
        token=make_ssdp_token(),
        soft_token=enrolled_soft_token() if enrolled else None,
    )


class FakeSsdpClient:
    """A stellantis_ssdp.Client built by FakeSsdpClientFactory"""

    def __init__(
        self, factory: FakeSsdpClientFactory, args: tuple[Any, ...], kwargs: Any
    ) -> None:
        self.factory = factory
        self.brand, self.state = args
        self.kwargs = kwargs
        self.vehicles: dict[str, SsdpVehicle] = {}
        self.refresh = AsyncMock(side_effect=self._refresh)
        self.command_verify = AsyncMock(return_value="RA1")
        self.enroll_start = AsyncMock()
        self.enroll_finish = AsyncMock(side_effect=self._enroll_finish)
        self.set_pin = MagicMock()

    @property
    def enrolled(self) -> bool:
        return self.state.enrolled

    async def _refresh(self) -> dict[str, SsdpVehicle]:
        items = self.factory.list_items
        for item in items:
            vehicle = self.vehicles.get(item["vin"]) or SsdpVehicle(vin=item["vin"])
            apply_ssdp_list_item(vehicle, item)
            if (telemetry := self.factory.telemetry.get(item["vin"])) is not None:
                apply_telemetry(vehicle, copy.deepcopy(telemetry))
            self.vehicles[item["vin"]] = vehicle

        vins = {item["vin"] for item in items}
        for vin in list(self.vehicles):
            if vin not in vins:
                del self.vehicles[vin]

        return self.vehicles

    async def _enroll_finish(self, code: str, pin: str) -> None:
        self.state.soft_token = enrolled_soft_token()
        self.state.remote_token = make_ssdp_token("RCZ")
        if callback := self.kwargs.get("on_state_change"):
            callback(self.state)


class FakeSsdpClientFactory:
    """Replaces stellantis_ssdp.Client: every entry gets its own client, all
    of them return the vehicles of list_items/telemetry"""

    def __init__(self) -> None:
        self.list_items: list[dict[str, Any]] = load_fixture("ssdp_vehicles.json")[
            "_embedded"
        ]["vehicles"]
        self.telemetry: dict[str, dict[str, Any]] = {
            SSDP_VIN: load_fixture("ssdp_telemetry.json")
        }
        self.instances: list[FakeSsdpClient] = []

    def __call__(self, *args: Any, **kwargs: Any) -> FakeSsdpClient:
        client = FakeSsdpClient(self, args, kwargs)
        self.instances.append(client)
        return client

    @property
    def last(self) -> FakeSsdpClient:
        return self.instances[-1]


@pytest.fixture
def ssdp_client() -> Iterator[FakeSsdpClientFactory]:
    factory = FakeSsdpClientFactory()
    with patch("custom_components.uconnect.ssdp.coordinator.Client", factory):
        yield factory


def make_ssdp_entry(
    brand: int = SSDP_BRAND,
    enrolled: bool = True,
    command_entities: bool = True,
    username: str = "user@example.com",
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"{BRANDS[brand]} {username}",
        unique_id=entry_unique_id(brand, username),
        data={
            CONF_USERNAME: username,
            CONF_PASSWORD: "secret",
            CONF_BRAND_REGION: brand,
            CONF_PIN: "1234",
            CONF_DISABLE_TLS_VERIFICATION: False,
            CONF_SSDP_STATE: make_ssdp_state(enrolled).to_dict(),
        },
        options={
            CONF_SCAN_INTERVAL: 5,
            CONF_PIN: "",
            CONF_ADD_COMMAND_ENTITIES: command_entities,
        },
    )


@pytest.fixture
def ssdp_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = make_ssdp_entry()
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_ssdp_integration(
    hass: HomeAssistant,
    ssdp_config_entry: MockConfigEntry,
    ssdp_client: FakeSsdpClientFactory,
) -> AsyncIterator[MockConfigEntry]:
    """Set up an entry of an SSDP brand and unload it after the test"""

    assert await hass.config_entries.async_setup(ssdp_config_entry.entry_id)
    await hass.async_block_till_done()

    yield ssdp_config_entry

    await hass.config_entries.async_unload(ssdp_config_entry.entry_id)
    await hass.async_block_till_done()
