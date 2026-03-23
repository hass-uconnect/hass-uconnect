"""Frontend (Lovelace) helpers for the Uconnect integration.

Provides:
- A websocket command returning discovered vehicles with entity mapping.
- Automatic registration of the card JS as a Lovelace resource.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_DATA_KEY = "_frontend_cards_setup"
_RESOURCE_ID_KEY = "_frontend_cards_resource_id"

_STATIC_BASE_URL = "/uconnect/uconnect-vehicle-card.js"
_STATIC_RELATIVE_PATH = Path(__file__).parent / "frontend" / "uconnect-vehicle-card.js"


async def _async_register_lovelace_resource(hass: HomeAssistant) -> str | None:
    """Register the card JS as a Lovelace resource.

    Defers loading of the ResourceStorageCollection to avoid corrupting
    existing resources when the collection has not been loaded from disk yet.
    """
    try:
        lovelace_data = hass.data.get("lovelace")
        if lovelace_data is None:
            _LOGGER.debug("Lovelace data not available, skipping resource registration")
            return None

        resources = getattr(lovelace_data, "resources", None)
        if resources is None:
            _LOGGER.debug(
                "Lovelace resources not available, skipping resource registration"
            )
            return None

        # Mirror the lazy-load guard that ResourceStorageCollection uses
        # internally.  Calling async_create_item() on an unloaded collection
        # would overwrite the storage file, destroying all existing resources.
        if hasattr(resources, "loaded") and not resources.loaded:
            await resources.async_load()
            resources.loaded = True

        for item in resources.async_items():
            if item.get("url") == _STATIC_BASE_URL:
                return item["id"]

        item = await resources.async_create_item(
            {"res_type": "module", "url": _STATIC_BASE_URL}
        )
        return item["id"]
    except Exception as err:
        _LOGGER.warning("Unable to register Lovelace resource: %s", err)
        return None


async def _async_unregister_lovelace_resource(
    hass: HomeAssistant, resource_id: str
) -> None:
    """Remove the Lovelace resource entry."""
    try:
        lovelace_data = hass.data.get("lovelace")
        if lovelace_data is None:
            return
        resources = getattr(lovelace_data, "resources", None)
        if resources is None:
            return
        await resources.async_delete_item(resource_id)
    except Exception as err:
        _LOGGER.debug("Unable to remove Lovelace resource %s: %s", resource_id, err)


async def async_setup_frontend_cards(hass: HomeAssistant) -> None:
    """Set up websocket API and register the card JS as a Lovelace resource.

    Safe to call multiple times across multiple config entries.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_DATA_KEY):
        return

    try:
        websocket_api.async_register_command(hass, websocket_vehicle_cards)
    except Exception as err:
        _LOGGER.debug("Unable to register websocket command: %s", err)

    try:
        from homeassistant.components.http import StaticPathConfig

        if not _STATIC_RELATIVE_PATH.exists():
            _LOGGER.warning(
                "Frontend card JS missing at %s; vehicle card unavailable",
                _STATIC_RELATIVE_PATH,
            )
        else:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(_STATIC_BASE_URL, str(_STATIC_RELATIVE_PATH), True)]
            )
            _LOGGER.debug("Registered static path %s", _STATIC_BASE_URL)
    except Exception as err:
        _LOGGER.debug("Unable to register static path: %s", err)

    # Defer Lovelace resource registration until HA is fully started.
    # During startup ResourceStorageCollection may not be loaded yet.
    async def _register_resource(_event: Any = None) -> None:
        resource_id = await _async_register_lovelace_resource(hass)
        if resource_id:
            domain_data[_RESOURCE_ID_KEY] = resource_id
            _LOGGER.debug("Registered Lovelace resource %s", resource_id)
        else:
            _LOGGER.debug("Lovelace resource registration returned None")

    if hass.state is CoreState.running:
        _LOGGER.debug("HA running, registering Lovelace resource now")
        await _register_resource()
    else:
        _LOGGER.debug("HA starting, deferring Lovelace resource registration")
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_resource)

    domain_data[_DATA_KEY] = True


async def async_unload_frontend_cards_if_last_entry(
    hass: HomeAssistant,
) -> None:
    """Remove the Lovelace resource if no Uconnect entries remain."""
    domain_data: dict[str, Any] | None = hass.data.get(DOMAIN)
    if not domain_data:
        return

    remaining_entries = [k for k in domain_data if not k.startswith("_")]
    if remaining_entries:
        return

    resource_id = domain_data.get(_RESOURCE_ID_KEY)
    if isinstance(resource_id, str) and resource_id:
        await _async_unregister_lovelace_resource(hass, resource_id)


# ---- Websocket API ----


def _build_unique_id_map(hass: HomeAssistant) -> dict[str, str]:
    """Build a mapping from unique_id to entity_id for uconnect entities."""
    try:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        mapping: dict[str, str] = {}
        for entry in registry.entities.values():
            if getattr(entry, "platform", None) != DOMAIN:
                continue
            if entry.unique_id and entry.entity_id:
                mapping[entry.unique_id] = entry.entity_id
        return mapping
    except Exception:
        return {}


def _normalize_vin_from_identifiers(
    identifiers: set[tuple[str, str]],
) -> str | None:
    for identifier in identifiers:
        if identifier[0] == DOMAIN and isinstance(identifier[1], str) and identifier[1]:
            return identifier[1]
    return None


def _build_vehicle_list(hass: HomeAssistant) -> list[dict[str, Any]]:
    from homeassistant.helpers import device_registry as dr

    dev_reg = dr.async_get(hass)
    unique_id_map = _build_unique_id_map(hass)

    vehicles: list[dict[str, Any]] = []
    for device in dev_reg.devices.values():
        vin = _normalize_vin_from_identifiers(device.identifiers)
        if not vin:
            continue

        name = device.name_by_user or device.name or vin
        device_id = getattr(device, "id", None)

        entities: dict[str, str] = {}

        # Simple key -> unique_id suffix mapping.
        # Unique IDs in hass-uconnect are "uconnect_{vin}_{key}".
        simple_mappings: list[tuple[str, str]] = [
            ("image", "image"),
            ("soc", "state_of_charge"),
            ("extrapolated_soc", "extrapolated_soc"),
            ("charging_rate", "charging_rate"),
            ("range", "distance_to_empty"),
            ("range_gas", "range_gas"),
            ("range_total", "range_total"),
            ("odometer", "odometer"),
            ("charging", "charging"),
            ("plugged_in", "plugged_in"),
            ("ignition", "ignition_on"),
            ("ev_running", "ev_running"),
            ("door_driver", "door_driver_locked"),
            ("door_passenger", "door_passenger_locked"),
            ("door_rear_left", "door_rear_left_locked"),
            ("door_rear_right", "door_rear_right_locked"),
            ("trunk", "trunk_locked"),
            ("window_driver", "window_driver_closed"),
            ("window_passenger", "window_passenger_closed"),
            ("tire_fl", "wheel_front_left_pressure"),
            ("tire_fr", "wheel_front_right_pressure"),
            ("tire_rl", "wheel_rear_left_pressure"),
            ("tire_rr", "wheel_rear_right_pressure"),
            ("tire_fl_warn", "wheel_front_left_pressure_warning"),
            ("tire_fr_warn", "wheel_front_right_pressure_warning"),
            ("tire_rl_warn", "wheel_rear_left_pressure_warning"),
            ("tire_rr_warn", "wheel_rear_right_pressure_warning"),
            ("fuel", "fuel_amount"),
            ("battery_voltage", "battery_voltage"),
            ("device_tracker", "location"),
        ]

        for card_key, suffix in simple_mappings:
            unique_id = f"{DOMAIN}_{vin}_{suffix}"
            entity_id = unique_id_map.get(unique_id)
            if entity_id:
                entities[card_key] = entity_id

        vehicles.append(
            {
                "vin": vin,
                "device_id": device_id,
                "name": name,
                "entities": entities,
            }
        )

    vehicles.sort(key=lambda v: str(v.get("name") or v.get("vin") or ""))
    return vehicles


@websocket_api.websocket_command({"type": "uconnect/vehicle_cards"})
@websocket_api.async_response
async def websocket_vehicle_cards(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return vehicles and entity mapping for frontend cards."""
    payload = {"vehicles": _build_vehicle_list(hass)}
    connection.send_result(msg["id"], payload)
