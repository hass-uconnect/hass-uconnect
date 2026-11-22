"""Binary sensors for Uconnect integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from py_uconnect import Vehicle

from .const import DOMAIN
from .coordinator import UconnectConfigEntry, UconnectDataUpdateCoordinator
from .entity import UconnectEntity, should_add


@dataclass(frozen=True, kw_only=True)
class UconnectBinarySensorEntityDescription(BinarySensorEntityDescription):
    """A class that describes custom binary sensor entities."""

    is_on: Callable[[Vehicle], bool | None] | None = None
    postprocess: Callable[[bool], bool] | None = None
    on_icon: str | None = None
    off_icon: str | None = None


SENSOR_DESCRIPTIONS: Final[tuple[UconnectBinarySensorEntityDescription, ...]] = (
    UconnectBinarySensorEntityDescription(
        key="ignition_on",
        translation_key="ignition_on",
        on_icon="mdi:engine",
        off_icon="mdi:engine-off",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    UconnectBinarySensorEntityDescription(
        key="ev_running",
        translation_key="ev_running",
        on_icon="mdi:engine",
        off_icon="mdi:engine-off",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    UconnectBinarySensorEntityDescription(
        key="door_driver_locked",
        translation_key="door_driver_locked",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door-lock",
        off_icon="mdi:car-door-lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    UconnectBinarySensorEntityDescription(
        key="door_passenger_locked",
        translation_key="door_passenger_locked",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door-lock",
        off_icon="mdi:car-door-lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    UconnectBinarySensorEntityDescription(
        key="door_rear_left_locked",
        translation_key="door_rear_left_locked",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door-lock",
        off_icon="mdi:car-door-lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    UconnectBinarySensorEntityDescription(
        key="door_rear_right_locked",
        translation_key="door_rear_right_locked",
        postprocess=lambda x: not x,
        on_icon="mdi:car-door-lock",
        off_icon="mdi:car-door-lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    UconnectBinarySensorEntityDescription(
        key="trunk_locked",
        translation_key="trunk_locked",
        postprocess=lambda x: not x,
        on_icon="mdi:lock",
        off_icon="mdi:lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    UconnectBinarySensorEntityDescription(
        key="window_driver_closed",
        translation_key="window_driver_closed",
        postprocess=lambda x: not x,
        on_icon="mdi:window-open",
        off_icon="mdi:window-closed",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    UconnectBinarySensorEntityDescription(
        key="window_passenger_closed",
        translation_key="window_passenger_closed",
        postprocess=lambda x: not x,
        on_icon="mdi:window-open",
        off_icon="mdi:window-closed",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    UconnectBinarySensorEntityDescription(
        key="window_rear_left_closed",
        translation_key="window_rear_left_closed",
        postprocess=lambda x: not x,
        on_icon="mdi:window-open",
        off_icon="mdi:window-closed",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    UconnectBinarySensorEntityDescription(
        key="window_rear_right_closed",
        translation_key="window_rear_right_closed",
        postprocess=lambda x: not x,
        on_icon="mdi:window-open",
        off_icon="mdi:window-closed",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    UconnectBinarySensorEntityDescription(
        key="sunroof_closed",
        translation_key="sunroof_closed",
        postprocess=lambda x: not x,
        on_icon="mdi:window-open",
        off_icon="mdi:window-closed",
        device_class=BinarySensorDeviceClass.WINDOW,
    ),
    UconnectBinarySensorEntityDescription(
        key="liftgate_locked",
        translation_key="liftgate_locked",
        postprocess=lambda x: not x,
        on_icon="mdi:lock",
        off_icon="mdi:lock-open",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    UconnectBinarySensorEntityDescription(
        key="hvac_on",
        translation_key="hvac_on",
        on_icon="mdi:hvac",
        off_icon="mdi:hvac-off",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    UconnectBinarySensorEntityDescription(
        key="plugged_in",
        translation_key="plugged_in",
        on_icon="mdi:power-plug",
        off_icon="mdi:power-plug-off",
        device_class=BinarySensorDeviceClass.PLUG,
    ),
    UconnectBinarySensorEntityDescription(
        key="charging",
        translation_key="charging",
        on_icon="mdi:battery-charging",
        off_icon="mdi:battery-alert",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    ),
    UconnectBinarySensorEntityDescription(
        key="wheel_front_left_pressure_warning",
        translation_key="wheel_front_left_pressure_warning",
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    UconnectBinarySensorEntityDescription(
        key="wheel_front_right_pressure_warning",
        translation_key="wheel_front_right_pressure_warning",
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    UconnectBinarySensorEntityDescription(
        key="wheel_rear_right_pressure_warning",
        translation_key="wheel_rear_right_pressure_warning",
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    UconnectBinarySensorEntityDescription(
        key="wheel_rear_left_pressure_warning",
        translation_key="wheel_rear_left_pressure_warning",
        on_icon="mdi:car-tire-alert",
        off_icon="mdi:car-tire-alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    UconnectBinarySensorEntityDescription(
        key="fuel_low",
        translation_key="fuel_low",
        on_icon="mdi:gas-station",
        off_icon="mdi:fuel",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    UconnectBinarySensorEntityDescription(
        key="ev_head_seat",
        translation_key="ev_head_seat",
        on_icon="mdi:car-seat-heater",
        off_icon="mdi:car-seat",
    ),
    UconnectBinarySensorEntityDescription(
        key="ev_cabin_cond",
        translation_key="ev_cabin_cond",
        on_icon="mdi:air-conditioner",
        off_icon="mdi:air-conditioner",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UconnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary_sensor platform."""

    coordinator = config_entry.runtime_data
    entities: list[BinarySensorEntity] = []

    for vehicle in coordinator.client.vehicles.values():
        for description in SENSOR_DESCRIPTIONS:
            if should_add(
                hass,
                Platform.BINARY_SENSOR,
                f"{DOMAIN}_{vehicle.vin}_{description.key}",
                getattr(vehicle, description.key, None) is not None,
            ):
                entities.append(UconnectBinarySensor(coordinator, description, vehicle))

        if should_add(
            hass,
            Platform.BINARY_SENSOR,
            f"{DOMAIN}_{vehicle.vin}_svla",
            vehicle.vin in coordinator.svla_data,
        ):
            entities.append(UconnectStolenVehicleSensor(coordinator, vehicle))

    async_add_entities(entities)


class UconnectBinarySensor(BinarySensorEntity, UconnectEntity):
    """Uconnect binary sensor class."""

    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        description: UconnectBinarySensorEntityDescription,
        vehicle: Vehicle,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle)
        self.key = description.key
        self.postprocess = description.postprocess
        self.entity_description: UconnectBinarySensorEntityDescription = description
        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""

        if self.entity_description.is_on is not None:
            v = self.entity_description.is_on(self.vehicle)
        else:
            v = getattr(self.vehicle, self.key)

        if v is not None and self.postprocess is not None:
            v = self.postprocess(v)

        return v

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""

        if self.entity_description.on_icon is None:
            return None

        return (
            self.entity_description.on_icon
            if self.is_on
            else self.entity_description.off_icon or self.entity_description.on_icon
        )


class UconnectStolenVehicleSensor(BinarySensorEntity, UconnectEntity):
    """Uconnect Stolen Vehicle Locator sensor."""

    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle)

        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_svla"
        self._attr_translation_key = "svla"
        self._attr_device_class = BinarySensorDeviceClass.SAFETY

    @property
    def is_on(self) -> bool | None:
        """Return true if the vehicle is reported stolen."""

        data = self.coordinator.svla_data.get(self._vin)
        if data is None:
            return None

        return data.get("svlaStatus")

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend."""

        return "mdi:shield-alert" if self.is_on else "mdi:shield-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the activation timestamp if available."""

        data = self.coordinator.svla_data.get(self._vin)
        if data is None:
            return None

        ts = data.get("activationTimestamp")
        if isinstance(ts, int | float) and ts > 0:
            return {
                "activation_timestamp": dt_util.as_local(
                    dt_util.utc_from_timestamp(ts / 1000)
                )
            }

        return None
