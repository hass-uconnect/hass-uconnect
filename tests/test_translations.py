"""Translations: the same keys in every language, translated entity names."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.uconnect.const import DOMAIN

from .conftest import ICE_VIN, FakeClient

TRANSLATIONS = (
    Path(__file__).parent.parent / "custom_components" / DOMAIN / "translations"
)


def keys(obj: object, prefix: str = "") -> set[str]:
    if not isinstance(obj, dict):
        return {prefix}
    return set().union(*(keys(v, f"{prefix}/{k}") for k, v in obj.items()))


def test_same_keys_in_every_language() -> None:
    english = keys(json.loads((TRANSLATIONS / "en.json").read_text()))
    for path in TRANSLATIONS.glob("*.json"):
        assert keys(json.loads(path.read_text())) == english, path.name


async def test_french_entity_names(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    """Names follow the language of Home Assistant, like the ids of new entities"""

    hass.config.language = "fr"

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{DOMAIN}_{ICE_VIN}_odometer"
    )
    assert entity_id == "sensor.jeep_wrangler_kilometrage"
    assert (
        hass.states.get(entity_id).attributes["friendly_name"]
        == "JEEP Wrangler Kilométrage"
    )

    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_existing_entity_ids_kept(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    """Entities created before keep their id when the names get translated"""

    unique_id = f"{DOMAIN}_{ICE_VIN}_odometer"
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        unique_id,
        config_entry=config_entry,
        suggested_object_id="jeep_wrangler_odometer",
    )
    hass.config.language = "fr"

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id == "sensor.jeep_wrangler_odometer"
    assert (
        hass.states.get(entity_id).attributes["friendly_name"]
        == "JEEP Wrangler Kilométrage"
    )

    await hass.config_entries.async_unload(config_entry.entry_id)
