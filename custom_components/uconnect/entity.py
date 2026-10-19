"""Base Entity for Uconnect integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from py_uconnect import Vehicle

from .const import DOMAIN
from .coordinator import UconnectDataUpdateCoordinator


def vehicle_name(vehicle: Vehicle) -> str:
    """Return the name of the vehicle, the prefix of its entity names."""

    return f"{vehicle.make} {vehicle.nickname or vehicle.model}"


def should_add(
    hass: HomeAssistant, platform: str, unique_id: str, supported: bool
) -> bool:
    """Return whether to create an entity.

    It is created if the vehicle provides it, or if it was created before: a
    value missing at startup (an endpoint failing, a state the vehicle reports
    as not available) must not make an existing entity disappear.
    """

    if supported:
        return True

    return (
        er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id) is not None
    )


class UconnectEntity(CoordinatorEntity[UconnectDataUpdateCoordinator]):
    """Class for base entity for Uconnect integration."""

    def __init__(
        self, coordinator: UconnectDataUpdateCoordinator, vehicle: Vehicle
    ) -> None:
        """Initialize the base entity."""
        super().__init__(coordinator)
        self._vin = vehicle.vin
        self._last_vehicle = vehicle

    @property
    def vehicle(self) -> Vehicle:
        """Get the current vehicle object from the coordinator.

        If the vehicle was removed from the account the last known object is
        returned and the entity is unavailable.
        """
        vehicle = self.coordinator.client.vehicles.get(self._vin)
        if vehicle is not None:
            self._last_vehicle = vehicle
        return self._last_vehicle

    @property
    def available(self) -> bool:
        """Return whether the vehicle is still in the account."""
        return super().available and self._vin in self.coordinator.client.vehicles

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information to use for this entity."""

        return DeviceInfo(
            identifiers={(DOMAIN, self.vehicle.vin)},
            manufacturer=self.vehicle.make,
            model=self.vehicle.model,
            name=vehicle_name(self.vehicle),
        )
