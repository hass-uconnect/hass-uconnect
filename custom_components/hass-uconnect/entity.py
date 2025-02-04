
"""Base Entity for Uconnect integration."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo

from py_uconnect.client import Vehicle

from .const import DOMAIN


class UconnectEntity(CoordinatorEntity):
    """Class for base entity for Uconnect integration."""

    def __init__(self, coordinator, vehicle):
        """Initialize the base entity."""
        super().__init__(coordinator)
        self.vehicle: Vehicle = vehicle

    @property
    def device_info(self):
        """Return device information to use for this entity."""

        return DeviceInfo(
            identifiers={(DOMAIN, self.vehicle.vin)},
            manufacturer=self.vehicle.make,
            model=self.vehicle.model,
            name=f"{self.vehicle.make} {
                self.vehicle.model}" or self.vehicle_nickname,
        )
