"""Entity states and actions."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from py_uconnect import ChargingLevel
from py_uconnect.command import (
    COMMAND_CHARGE,
    COMMAND_DOORS_UNLOCK,
    COMMAND_HVAC_OFF,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from pytest_homeassistant_custom_component.typing import (
    ClientSessionGenerator,
    WebSocketGenerator,
)

from custom_components.uconnect.const import DOMAIN
from custom_components.uconnect.frontend_cards import (
    async_setup_frontend_cards,
    async_unload_frontend_cards_if_last_entry,
)
from custom_components.uconnect.image import BROWSER_HEADERS

from .conftest import EV_VIN, ICE_VIN, IMAGE_URL, FakeClient

CARD_URL = "/uconnect/uconnect-vehicle-card.js"
PNG = b"\x89PNG\r\n\x1a\nimage"


def entity_id(hass: HomeAssistant, platform: str, vin: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{DOMAIN}_{vin}_{key}"
    )
    assert entity_id is not None, key
    return entity_id


def state(hass: HomeAssistant, platform: str, vin: str, key: str) -> str:
    return hass.states.get(entity_id(hass, platform, vin, key)).state


async def test_binary_sensors(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    def bs(key: str) -> str:
        return state(hass, "binary_sensor", EV_VIN, key)

    # on = unlocked / open
    assert bs("door_driver_locked") == STATE_OFF
    assert bs("door_rear_left_locked") == STATE_ON
    assert bs("window_driver_closed") == STATE_OFF
    assert bs("window_passenger_closed") == STATE_ON
    assert bs("window_rear_left_closed") == STATE_OFF
    assert bs("liftgate_locked") == STATE_ON
    assert bs("trunk_locked") == STATE_OFF
    assert bs("hvac_on") == STATE_ON
    assert bs("charging") == STATE_ON
    assert bs("svla") == STATE_OFF

    assert state(hass, "binary_sensor", ICE_VIN, "fuel_low") == STATE_OFF
    assert (
        state(hass, "binary_sensor", ICE_VIN, "wheel_rear_left_pressure_warning")
        == STATE_ON
    )


async def test_sensors(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    temperature = hass.states.get(entity_id(hass, "sensor", EV_VIN, "hvac_temperature"))
    assert temperature.state == "21.5"
    assert temperature.attributes["unit_of_measurement"] == "°C"

    assert state(hass, "sensor", EV_VIN, "privacy_mode") == "INACTIVE"
    assert state(hass, "sensor", EV_VIN, "state_of_charge") == "63"
    assert state(hass, "sensor", EV_VIN, "charging_level") == "2"
    assert state(hass, "sensor", EV_VIN, "fuel_type") == "E"
    assert state(hass, "sensor", EV_VIN, "timestamp_info") == (
        "2025-02-04T09:10:03+00:00"
    )

    pressure = hass.states.get(
        entity_id(hass, "sensor", EV_VIN, "wheel_front_left_pressure")
    )
    assert pressure.state == "250"
    assert pressure.attributes["unit_of_measurement"] == "kPa"

    vhr = hass.states.get(entity_id(hass, "sensor", EV_VIN, "vhr"))
    assert vhr.state == "2025-02-04T09:10:03+00:00"
    assert vhr.attributes["engine.oil"] == "OK"

    maintenance = hass.states.get(entity_id(hass, "sensor", EV_VIN, "maintenance"))
    assert maintenance.attributes["last_service_description"] == "Annual service"
    assert maintenance.attributes["total_records"] == 1


async def test_charge_schedule_sensor(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    schedule = hass.states.get(entity_id(hass, "sensor", EV_VIN, "charge_schedule"))

    assert schedule.state == "2"
    assert [s["scheduleType"] for s in schedule.attributes["schedules"]] == [
        "CHARGE",
        "CLIMATE",
    ]


async def test_device_tracker(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    tracker = hass.states.get(entity_id(hass, "device_tracker", EV_VIN, "location"))

    assert tracker.attributes["latitude"] == 45.0703
    assert tracker.attributes["longitude"] == 7.6869


async def test_switch_states(
    hass: HomeAssistant, fake_client: FakeClient, config_entry: MockConfigEntry
) -> None:
    fake_client.add_services(EV_VIN, "ROHVACON", "ROHVACOFF")
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Previously unknown, now from the remote status
    assert state(hass, "switch", EV_VIN, "switch_hvac") == STATE_ON
    assert state(hass, "switch", EV_VIN, "switch_trunk") == STATE_ON
    assert state(hass, "switch", EV_VIN, "switch_charging") == STATE_ON
    # Not reported by the vehicle
    assert state(hass, "switch", EV_VIN, "switch_precondition") == STATE_UNKNOWN

    await hass.services.async_call(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: entity_id(hass, "switch", EV_VIN, "switch_hvac")},
        blocking=True,
    )
    fake_client.command_verify.assert_awaited_once_with(EV_VIN, COMMAND_HVAC_OFF, None)

    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_switch_without_command(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    with pytest.raises(HomeAssistantError, match="cannot be turned off"):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {ATTR_ENTITY_ID: entity_id(hass, "switch", EV_VIN, "switch_charging")},
            blocking=True,
        )


async def test_lock(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    lock = entity_id(hass, "lock", EV_VIN, "lock_doors")
    assert hass.states.get(lock).state == "locked"

    await hass.services.async_call(
        "lock", "unlock", {ATTR_ENTITY_ID: lock}, blocking=True
    )

    fake_client.command_verify.assert_awaited_once_with(
        EV_VIN, COMMAND_DOORS_UNLOCK, None
    )


async def test_lock_failure(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.command_verify.return_value = False

    with pytest.raises(HomeAssistantError, match="Failed to unlock"):
        await hass.services.async_call(
            "lock",
            "unlock",
            {ATTR_ENTITY_ID: entity_id(hass, "lock", EV_VIN, "lock_doors")},
            blocking=True,
        )


async def test_button(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: entity_id(hass, "button", EV_VIN, "button_charge")},
        blocking=True,
    )

    fake_client.command_verify.assert_awaited_once_with(EV_VIN, COMMAND_CHARGE, None)


async def test_charging_level_select(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    select = entity_id(hass, "select", EV_VIN, "charging_level_preference")
    current = hass.states.get(select)
    assert current.state == "LEVEL_FIVE"
    assert current.attributes["options"] == [x.value for x in ChargingLevel]

    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: select, "option": "LEVEL_TWO"},
        blocking=True,
    )

    fake_client.set_charging_level_verify.assert_awaited_once_with(
        EV_VIN, ChargingLevel.LEVEL_TWO
    )


async def test_images(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    # The Fiat has an image URL in the vehicle list, the Jeep gets it from
    # the image endpoint
    fake_client.api.get_vehicle_image.assert_awaited_once_with(ICE_VIN)
    assert hass.states.get(entity_id(hass, "image", ICE_VIN, "image")) is not None


@pytest.fixture
def image_cache(tmp_path: Path) -> Iterator[None]:
    """Keep the downloaded images out of the shared test config directory"""

    with patch("custom_components.uconnect.image.CACHE_DIR", str(tmp_path)):
        yield


async def _get_image(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> tuple[int, str, bytes]:
    image = hass.states.get(entity_id(hass, "image", ICE_VIN, "image"))
    client = await hass_client()
    resp = await client.get(image.attributes["entity_picture"])
    return resp.status, resp.content_type, await resp.read()


async def test_image_user_agent_fallback(
    hass: HomeAssistant,
    image_cache: None,
    aioclient_mock: AiohttpClientMocker,
    setup_integration: MockConfigEntry,
    hass_client: ClientSessionGenerator,
) -> None:
    # Some image CDNs reject the browser User-Agent, without telling the
    # content type of the image once it is accepted
    async def respond(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        if len(aioclient_mock.mock_calls) == 1:
            return AiohttpClientMockResponse(method, url, status=403)
        return AiohttpClientMockResponse(
            method,
            url,
            response=PNG,
            headers={"Content-Type": "application/octet-stream"},
        )

    aioclient_mock.get(IMAGE_URL, side_effect=respond)

    status, content_type, body = await _get_image(hass, hass_client)

    assert status == 200
    assert body == PNG
    assert content_type.startswith("image/")

    first, second = (call[3] for call in aioclient_mock.mock_calls)
    assert first["User-Agent"] == BROWSER_HEADERS["User-Agent"]
    assert "User-Agent" not in second


async def test_image_error_not_retried(
    hass: HomeAssistant,
    image_cache: None,
    aioclient_mock: AiohttpClientMocker,
    setup_integration: MockConfigEntry,
    hass_client: ClientSessionGenerator,
) -> None:
    aioclient_mock.get(IMAGE_URL, status=500)

    status, _, _ = await _get_image(hass, hass_client)

    assert status != 200
    assert aioclient_mock.call_count == 1


async def test_vehicle_card_websocket(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "uconnect/vehicle_cards"})
    response = await client.receive_json()

    assert response["success"]
    vehicles = {v["vin"]: v for v in response["result"]["vehicles"]}
    assert set(vehicles) == {EV_VIN, ICE_VIN}

    entities = vehicles[EV_VIN]["entities"]
    assert entities["soc"] == entity_id(hass, "sensor", EV_VIN, "state_of_charge")
    assert entities["window_rear_left"] == entity_id(
        hass, "binary_sensor", EV_VIN, "window_rear_left_closed"
    )
    assert entities["liftgate"] == entity_id(
        hass, "binary_sensor", EV_VIN, "liftgate_locked"
    )
    assert "sunroof" not in entities


async def test_vehicle_card_yaml_dashboards(hass: HomeAssistant) -> None:
    # Resources can't be added to dashboards in YAML mode, the card is
    # loaded as an extra frontend module instead
    hass.data["lovelace"] = SimpleNamespace(
        resources=SimpleNamespace(async_items=lambda: [])
    )

    with (
        patch("custom_components.uconnect.frontend_cards.add_extra_js_url") as add,
        patch(
            "custom_components.uconnect.frontend_cards.remove_extra_js_url"
        ) as remove,
    ):
        await async_setup_frontend_cards(hass)
        add.assert_called_once_with(hass, CARD_URL)

        await async_unload_frontend_cards_if_last_entry(hass)
        remove.assert_called_once_with(hass, CARD_URL)


async def test_vehicle_card_storage_dashboards(hass: HomeAssistant) -> None:
    resources = SimpleNamespace(
        loaded=True,
        async_items=lambda: [],
        async_create_item=AsyncMock(return_value={"id": "card"}),
        async_delete_item=AsyncMock(),
    )
    hass.data["lovelace"] = SimpleNamespace(resources=resources)

    with patch("custom_components.uconnect.frontend_cards.add_extra_js_url") as add:
        await async_setup_frontend_cards(hass)
        await async_unload_frontend_cards_if_last_entry(hass)

    resources.async_create_item.assert_awaited_once_with(
        {"res_type": "module", "url": CARD_URL}
    )
    resources.async_delete_item.assert_awaited_once_with("card")
    add.assert_not_called()
