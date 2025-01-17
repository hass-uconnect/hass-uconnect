
"""Base Entity for Fiat integration."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo

from pyfiat.client import Vehicle

from .const import DOMAIN


class FiatEntity(CoordinatorEntity):
    """Class for base entity for Fiat integration."""

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
            model=self.vehicle.make,
            name=f"{self.vehicle.make} {
                self.vehicle.nickname or self.vehicle.model}",
        )
