"""Image platform for Uconnect integration."""

from __future__ import annotations

import logging
from pathlib import Path

import aiohttp

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from py_uconnect.client import Vehicle

from .const import DOMAIN
from .coordinator import UconnectDataUpdateCoordinator
from .entity import UconnectEntity

_LOGGER = logging.getLogger(DOMAIN)

CACHE_DIR = ".storage/uconnect"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Uconnect image entities."""
    coordinator: UconnectDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.unique_id
    ]

    entities = []
    for vehicle in coordinator.client.get_vehicles().values():
        image_url = getattr(vehicle, "image_url", None)

        if not image_url:
            # Try the dedicated image API endpoint
            try:
                result = await hass.async_add_executor_job(
                    coordinator.client.get_vehicle_image, vehicle.vin
                )
                _LOGGER.debug(
                    "get_vehicle_image response for %s: %s", vehicle.vin, result
                )
                if isinstance(result, dict):
                    items = result.get("items")
                    if isinstance(items, list) and items:
                        image_url = items[0].get("preciseImageURL")
            except Exception as err:
                _LOGGER.error(
                    "Error calling get_vehicle_image for %s: %s: %s",
                    vehicle.vin,
                    type(err).__name__,
                    err,
                )

        if image_url:
            entities.append(UconnectVehicleImage(coordinator, vehicle, hass, image_url))

    async_add_entities(entities)


class UconnectVehicleImage(UconnectEntity, ImageEntity):
    """Representation of a Uconnect vehicle image."""

    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
        hass: HomeAssistant,
        image_url: str,
    ) -> None:
        """Initialize the image entity."""
        UconnectEntity.__init__(self, coordinator, vehicle)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_image"
        self._attr_name = f"{vehicle.make} {vehicle.nickname or vehicle.model} Image"
        self._attr_icon = "mdi:car"
        self._image_url = image_url
        cache_dir = Path(hass.config.path(CACHE_DIR))
        self._cache_path = cache_dir / f"{vehicle.vin}.img"
        self._url_path = cache_dir / f"{vehicle.vin}.url"
        self._cached_url: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore cached image state on startup."""
        await super().async_added_to_hass()
        cached_url = await self.hass.async_add_executor_job(self._read_cached_url)
        if cached_url and cached_url == self._image_url:
            self._cached_url = cached_url
        self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Invalidate cache when image URL changes."""
        url = self._image_url
        if url and self._cached_url and url != self._cached_url:
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        """Return vehicle image bytes, downloading and caching as needed."""
        url = self._image_url
        if not url:
            return None

        # Serve from disk cache if URL matches
        if url == self._cached_url:
            data = await self.hass.async_add_executor_job(self._read_cache)
            if data is not None:
                return data

        # Download and cache
        data = await self._fetch_image(url)
        if data is not None:
            await self.hass.async_add_executor_job(self._write_cache, data, url)
            self._cached_url = url
            return data

        # Fall back to stale cache on download failure
        return await self.hass.async_add_executor_job(self._read_cache)

    async def _fetch_image(self, url: str) -> bytes | None:
        """Download image from URL."""
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "Failed to fetch vehicle image: HTTP %s", resp.status
                    )
                    return None
                data = await resp.read()
                if resp.content_type:
                    self._attr_content_type = resp.content_type
                return data
        except Exception:
            _LOGGER.exception("Error fetching vehicle image")
            return None

    def _read_cache(self) -> bytes | None:
        """Read cached image from disk."""
        if self._cache_path.is_file():
            return self._cache_path.read_bytes()
        return None

    def _read_cached_url(self) -> str | None:
        """Read the URL of the cached image."""
        if self._url_path.is_file():
            return self._url_path.read_text().strip()
        return None

    def _write_cache(self, data: bytes, url: str) -> None:
        """Write image and its source URL to disk."""
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_bytes(data)
        self._url_path.write_text(url)
