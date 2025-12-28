"""Base Entity for Uconnect integration."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo

from py_uconnect.client import Vehicle

from .const import DOMAIN
from .coordinator import UconnectDataUpdateCoordinator


class UconnectEntity(CoordinatorEntity):
    """Class for base entity for Uconnect integration."""

    def __init__(self, coordinator: UconnectDataUpdateCoordinator, vehicle: Vehicle):
        """Initialize the base entity."""
        super().__init__(coordinator)
        self._vin = vehicle.vin

    @property
    def vehicle(self) -> Vehicle:
        """Get the current vehicle object from the coordinator."""
        return self.coordinator.client.get_vehicles()[self._vin]

    @property
    def device_info(self):
        """Return device information to use for this entity."""

        return DeviceInfo(
            identifiers={(DOMAIN, self.vehicle.vin)},
            manufacturer=self.vehicle.make,
            model=self.vehicle.model,
            name=f"{self.vehicle.make} {self.vehicle.nickname or self.vehicle.model}",
        )
