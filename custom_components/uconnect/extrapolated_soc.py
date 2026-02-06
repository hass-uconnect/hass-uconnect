"""Extrapolated State of Charge sensor for Uconnect integration.

This sensor predicts the battery charge level even when no data is received
from the vehicle, based on charging status and time-to-full estimates.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import callback
from homeassistant.helpers.event import (
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity

from py_uconnect.command import COMMAND_DEEP_REFRESH

from py_uconnect.client import Vehicle

from .const import DOMAIN
from .coordinator import UconnectDataUpdateCoordinator
from .entity import UconnectEntity

_LOGGER = logging.getLogger(__name__)

# Constants for SOC estimation
EXTRAPOLATION_UPDATE_INTERVAL = timedelta(minutes=1)  # Update extrapolated value every minute
STALE_THRESHOLD_HOURS = 2.0  # Stop extrapolating after this many hours without update
DEFAULT_CORRECTION_FACTOR = 1.0  # Default correction factor (no correction)
MIN_CORRECTION_FACTOR = 0.5  # Minimum allowed correction factor
MAX_CORRECTION_FACTOR = 1.5  # Maximum allowed correction factor
CORRECTION_EMA_ALPHA = 0.3  # Exponential moving average factor for correction learning
MIN_TIME_FOR_LEARNING_HOURS = 0.05  # Minimum 3 minutes for learning
MIN_SOC_CHANGE_FOR_LEARNING = 0.5  # Minimum 0.5% SOC change for learning

# Constants for idle drain estimation
DEFAULT_IDLE_DRAIN_RATE = 0.006  # Default 0.006%/hour ≈ 1%/week ≈ 4%/month
MIN_IDLE_DRAIN_RATE = 0.0  # Minimum drain rate
MAX_IDLE_DRAIN_RATE = 0.04  # Maximum drain rate (0.04%/hour ≈ 1%/day)
MIN_IDLE_TIME_FOR_LEARNING_HOURS = 1.0  # Minimum 1 hour idle for learning drain rate
IDLE_DRAIN_EMA_ALPHA = 0.2  # Slower learning for drain rate (less frequent data points)

# Constants for daily deep refresh
DEEP_REFRESH_HOUR_START = 2  # Start of window for daily deep refresh (2 AM)
DEEP_REFRESH_HOUR_END = 5  # End of window for daily deep refresh (5 AM)


@dataclass
class SocEstimationState:
    """State for SOC estimation."""

    last_actual_soc: float | None = None
    last_actual_soc_time: datetime | None = None
    is_charging: bool = False
    is_idle: bool = False  # Not charging and ignition off
    charging_rate_pct_per_hour: float = 0.0
    idle_drain_rate_pct_per_hour: float = DEFAULT_IDLE_DRAIN_RATE
    learned_correction_factor: float = DEFAULT_CORRECTION_FACTOR
    target_soc: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary for storage."""
        return {
            "last_actual_soc": self.last_actual_soc,
            "last_actual_soc_time": (
                self.last_actual_soc_time.isoformat()
                if self.last_actual_soc_time
                else None
            ),
            "is_charging": self.is_charging,
            "is_idle": self.is_idle,
            "charging_rate_pct_per_hour": self.charging_rate_pct_per_hour,
            "idle_drain_rate_pct_per_hour": self.idle_drain_rate_pct_per_hour,
            "learned_correction_factor": self.learned_correction_factor,
            "target_soc": self.target_soc,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SocEstimationState":
        """Create state from dictionary.

        Validates types to handle corrupted state gracefully.
        """
        if not isinstance(data, dict):
            return cls()

        # Parse last_actual_soc (must be float 0-100 or None)
        last_soc = data.get("last_actual_soc")
        if last_soc is not None and not isinstance(last_soc, (int, float)):
            last_soc = None
        if last_soc is not None:
            last_soc = max(0.0, min(100.0, last_soc))

        # Parse timestamp (must be timezone-aware for UTC arithmetic)
        last_time = data.get("last_actual_soc_time")
        last_time_parsed = None
        if isinstance(last_time, str):
            try:
                parsed = datetime.fromisoformat(last_time)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                last_time_parsed = parsed
            except ValueError:
                pass

        # Handle migration from old "learned_efficiency" to new "learned_correction_factor"
        correction = data.get(
            "learned_correction_factor",
            data.get("learned_efficiency", DEFAULT_CORRECTION_FACTOR)
        )
        if not isinstance(correction, (int, float)):
            correction = DEFAULT_CORRECTION_FACTOR
        correction = max(MIN_CORRECTION_FACTOR, min(MAX_CORRECTION_FACTOR, correction))

        # Parse drain rate with validation
        drain_rate = data.get("idle_drain_rate_pct_per_hour", DEFAULT_IDLE_DRAIN_RATE)
        if not isinstance(drain_rate, (int, float)):
            drain_rate = DEFAULT_IDLE_DRAIN_RATE
        drain_rate = max(MIN_IDLE_DRAIN_RATE, min(MAX_IDLE_DRAIN_RATE, drain_rate))

        # Parse charging rate with validation
        charging_rate = data.get("charging_rate_pct_per_hour", 0.0)
        if not isinstance(charging_rate, (int, float)):
            charging_rate = 0.0
        charging_rate = max(0.0, min(300.0, charging_rate))

        # Parse target SOC with validation (must be between 0 and 100)
        target_soc = data.get("target_soc", 100.0)
        if not isinstance(target_soc, (int, float)) or target_soc <= 0 or target_soc > 100:
            target_soc = 100.0

        return cls(
            last_actual_soc=float(last_soc) if last_soc is not None else None,
            last_actual_soc_time=last_time_parsed,
            is_charging=bool(data.get("is_charging", False)),
            is_idle=bool(data.get("is_idle", False)),
            charging_rate_pct_per_hour=float(charging_rate),
            idle_drain_rate_pct_per_hour=float(drain_rate),
            learned_correction_factor=float(correction),
            target_soc=float(target_soc),
        )


def select_time_to_full(
    charging_level: str | int | None,
    time_l2: float | None,
    time_l3: float | None,
) -> float | None:
    """Select the appropriate time-to-full value based on charging_level.

    Uses the charging_level sensor to determine which charger is connected,
    falling back to heuristics if not available.
    """
    valid_l2 = time_l2 is not None and time_l2 > 0
    valid_l3 = time_l3 is not None and time_l3 > 0

    # Use charging_level to select the right time-to-full
    if charging_level is not None:
        # Handle both int and string types
        level_str = str(charging_level).upper()
        if "3" in level_str or "DC" in level_str or "FAST" in level_str:
            if valid_l3:
                return time_l3
        elif "2" in level_str or "AC" in level_str:
            if valid_l2:
                return time_l2

    # Fallback: use whichever is available
    if valid_l2 and valid_l3:
        # Both available - use the smaller one (likely the active charger)
        return min(time_l2, time_l3)
    elif valid_l3:
        return time_l3
    elif valid_l2:
        return time_l2
    return None


def calculate_charging_rate(
    current_soc: float,
    time_to_full_minutes: float | None,
) -> float:
    """Calculate charging rate in percentage per hour.

    Uses the time-to-full estimate from the vehicle. The vehicle's estimate
    already accounts for the CC-CV (constant current/constant voltage) taper
    behavior, so we calculate a simple average rate.

    Assumptions:
    - time_to_full_minutes represents time to reach 100% SOC
    - If the vehicle actually reports time to reach target SOC (not 100%),
      this calculation will overestimate the rate. The learned correction
      factor should compensate for this over time.

    Note: This rate represents the average charging speed over the remaining
    charge time, which naturally decreases as SOC increases (since more of
    the remaining time is in the slower taper phase above 80%).
    """
    # Require at least 1 minute to avoid unrealistic rates from tiny values
    if time_to_full_minutes is None or time_to_full_minutes < 1.0:
        return 0.0

    remaining_soc = 100.0 - current_soc
    if remaining_soc <= 0:
        return 0.0

    time_to_full_hours = time_to_full_minutes / 60.0

    # Simple average rate: remaining SOC divided by time to reach 100%
    # The vehicle's time-to-full already accounts for taper behavior
    rate = remaining_soc / time_to_full_hours

    # Cap at 300%/hour (realistic max for fastest DC charging)
    return min(rate, 300.0)


class UconnectExtrapolatedSocSensor(RestoreEntity, SensorEntity, UconnectEntity):
    """Sensor that extrapolates battery SOC between updates."""

    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
    ) -> None:
        """Initialize the sensor."""
        # Explicitly initialize UconnectEntity to ensure coordinator subscription
        UconnectEntity.__init__(self, coordinator, vehicle)

        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_extrapolated_soc"
        self._attr_name = (
            f"{vehicle.make} {vehicle.nickname or vehicle.model} "
            "Extrapolated Battery"
        )
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:battery-sync"

        self._state = SocEstimationState()
        self._unsub_timer: Callable[[], None] | None = None
        self._unsub_deep_refresh: Callable[[], None] | None = None
        self._deep_refresh_hour: int = random.randint(
            DEEP_REFRESH_HOUR_START, DEEP_REFRESH_HOUR_END
        )
        self._deep_refresh_minute: int = random.randint(0, 59)

    async def async_added_to_hass(self) -> None:
        """Restore state when added to hass."""
        await super().async_added_to_hass()

        # Restore previous state
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.attributes.get("estimation_state"):
                try:
                    self._state = SocEstimationState.from_dict(
                        last_state.attributes["estimation_state"]
                    )
                    _LOGGER.debug(
                        "Restored SOC estimation state for %s: %s",
                        self.vehicle.vin,
                        self._state,
                    )
                except (KeyError, TypeError, ValueError) as err:
                    _LOGGER.warning(
                        "Failed to restore SOC estimation state: %s", err
                    )

        # Initialize with current vehicle state
        self._update_from_vehicle()

        # Set up periodic timer for extrapolation updates
        self._unsub_timer = async_track_time_interval(
            self.hass,
            self._async_update_extrapolation,
            EXTRAPOLATION_UPDATE_INTERVAL,
        )

        # Set up daily deep refresh at random time between 2-5 AM
        self._unsub_deep_refresh = async_track_time_change(
            self.hass,
            self._async_daily_deep_refresh,
            hour=self._deep_refresh_hour,
            minute=self._deep_refresh_minute,
            second=0,
        )
        _LOGGER.info(
            "Scheduled daily deep refresh for %s at %02d:%02d",
            self.vehicle.vin,
            self._deep_refresh_hour,
            self._deep_refresh_minute,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up timers when entity is removed."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        if self._unsub_deep_refresh:
            self._unsub_deep_refresh()
            self._unsub_deep_refresh = None
        await super().async_will_remove_from_hass()

    @callback
    def _async_update_extrapolation(self, _now: datetime) -> None:
        """Periodically update the extrapolated value."""
        # Update if charging or idle (both need extrapolation)
        if (
            (self._state.is_charging and self._state.charging_rate_pct_per_hour > 0)
            or (self._state.is_idle and self._state.idle_drain_rate_pct_per_hour > 0)
        ):
            self.async_write_ha_state()

    async def _async_daily_deep_refresh(self, _now: datetime) -> None:
        """Trigger daily deep refresh to get fresh SOC data for learning.

        Only refreshes if the car hasn't been powered on in the last 24 hours,
        since driving would provide fresh data anyway.
        """
        now = datetime.now(timezone.utc)
        hours_since_update = self._get_elapsed_hours(now)

        if hours_since_update is None:
            return

        if hours_since_update < 24.0:
            _LOGGER.debug(
                "Skipping daily deep refresh for %s - last update was %.1f hours ago",
                self.vehicle.vin,
                hours_since_update,
            )
            return

        _LOGGER.info("Triggering daily deep refresh for %s", self.vehicle.vin)
        try:
            await self.coordinator.async_command(self.vehicle.vin, COMMAND_DEEP_REFRESH)
        except Exception as err:
            _LOGGER.warning("Daily deep refresh failed for %s: %s", self.vehicle.vin, err)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_from_vehicle()
        self.async_write_ha_state()

    def _update_from_vehicle(self) -> None:
        """Update estimation state from vehicle data."""
        current_soc = getattr(self.vehicle, "state_of_charge", None)
        is_charging = getattr(self.vehicle, "charging", False) or False
        ignition_on = getattr(self.vehicle, "ignition_on", False) or False
        charging_level = getattr(self.vehicle, "charging_level", None)
        time_to_full_l2 = getattr(self.vehicle, "time_to_fully_charge_l2", None)
        time_to_full_l3 = getattr(self.vehicle, "time_to_fully_charge_l3", None)

        # Select the appropriate time-to-full based on charging_level sensor
        time_to_full = select_time_to_full(
            charging_level, time_to_full_l2, time_to_full_l3
        )

        now = datetime.now(timezone.utc)

        # Track if we're skipping due to stale charging data
        skip_stale_charging_data = False

        if current_soc is not None:
            # Only update baseline if SOC actually changed
            # This preserves extrapolation continuity across HA restarts
            soc_changed = (
                self._state.last_actual_soc is None
                or current_soc != self._state.last_actual_soc
            )

            # Only update SOC when charging/driving and new value exceeds extrapolated
            # When idle (parked), car data is stale and shouldn't reset extrapolation
            # Only skip if car WAS idle AND IS STILL idle - any state transition
            # (idle→driving or driving→idle) means fresh data
            current_extrapolated = self.native_value
            is_idle = not is_charging and not ignition_on

            # Physical constraint: SOC cannot drop while already charging
            # Uses stored state (was already charging) not current API state,
            # so idle→charging transitions with lower SOC from idle drain are accepted
            if (
                soc_changed
                and self._state.is_charging  # Was already charging
                and self._state.last_actual_soc is not None
                and current_soc < self._state.last_actual_soc
            ):
                _LOGGER.debug(
                    "Rejecting SOC drop during charging for %s: "
                    "reported %.1f%% but last known was %.1f%%",
                    self.vehicle.vin,
                    current_soc,
                    self._state.last_actual_soc,
                )
                soc_changed = False
                skip_stale_charging_data = True

            if soc_changed and self._state.is_idle and is_idle:
                # Accept SOC at or below extrapolation (confirms drain, likely fresh data)
                # Reject SOC above extrapolation (stale - can't gain charge while idle)
                if current_extrapolated is not None and current_soc <= current_extrapolated:
                    _LOGGER.debug(
                        "Accepting idle SOC update for %s: "
                        "%.1f%% confirms drain (extrapolated %.1f%%)",
                        self.vehicle.vin,
                        current_soc,
                        current_extrapolated,
                    )
                else:
                    _LOGGER.debug(
                        "Skipping idle SOC update for %s: "
                        "%.1f%% above extrapolated (stale data)",
                        self.vehicle.vin,
                        current_soc,
                    )
                    soc_changed = False
            elif (
                soc_changed
                and self._state.is_charging  # Was charging
                and is_charging  # Still charging (not a state transition)
                and current_extrapolated is not None
                and current_soc < current_extrapolated
            ):
                # Vehicle reports lower SOC than extrapolated while still charging
                # This is stale data - skip the entire update including state changes
                _LOGGER.debug(
                    "Skipping stale charging data for %s: car reports %.1f%% but extrapolated is %.1f%%",
                    self.vehicle.vin,
                    current_soc,
                    current_extrapolated,
                )
                soc_changed = False
                skip_stale_charging_data = True

        # Save previous state for learning
        was_charging = self._state.is_charging
        was_idle = self._state.is_idle

        # Update charging and idle state (unless we detected stale charging data)
        # Skip when current_soc is None to preserve restored state after reboot
        if current_soc is not None and not skip_stale_charging_data:
            self._state.is_charging = is_charging
            self._state.is_idle = not is_charging and not ignition_on

        # Always try to learn from SOC changes, even if we don't update baseline
        # This ensures deep refresh data is used for learning drain rate
        # But skip learning from stale data
        if (
            current_soc is not None
            and self._state.last_actual_soc is not None
            and not skip_stale_charging_data
        ):
            if current_soc != self._state.last_actual_soc:
                # Learn correction factor from actual vs predicted changes
                self._learn_correction_factor(current_soc, now, was_charging)
                # Learn drain rate from actual vs predicted changes when idle
                self._learn_drain_rate(current_soc, now, was_idle)

        # Only update baseline if soc_changed (respects skip logic above)
        if current_soc is not None and soc_changed:
            self._state.last_actual_soc = current_soc
            self._state.last_actual_soc_time = now

        # Calculate charging rate if charging with valid data
        # Don't recalculate if we detected stale charging data
        # Skip when current_soc is None to preserve restored rate after reboot
        if current_soc is not None and not skip_stale_charging_data:
            if is_charging and time_to_full is not None:
                self._state.charging_rate_pct_per_hour = calculate_charging_rate(
                    current_soc, time_to_full
                )
            else:
                # Zero rate when not charging OR when missing required data
                self._state.charging_rate_pct_per_hour = 0.0

        # Default target SOC to 100% (no target SOC limit for this vehicle type)
        self._state.target_soc = 100.0

    def _learn_correction_factor(
        self,
        current_soc: float,
        now: datetime,
        was_charging: bool,
    ) -> None:
        """Learn a correction factor by comparing actual vs predicted SOC changes.

        This helps account for discrepancies between the vehicle's time-to-full
        estimate and actual charging behavior.
        """
        if (
            self._state.last_actual_soc is None
            or not was_charging
            or self._state.charging_rate_pct_per_hour <= 0
        ):
            return

        elapsed_hours = self._get_elapsed_hours(now)

        # Guard against clock drift (NTP adjustments, etc.)
        if elapsed_hours is None or elapsed_hours < MIN_TIME_FOR_LEARNING_HOURS:
            return

        actual_change = current_soc - self._state.last_actual_soc

        # Only learn from meaningful positive changes (charging)
        if actual_change < MIN_SOC_CHANGE_FOR_LEARNING:
            return

        # Calculate what we expected based on the rate
        expected_change = self._state.charging_rate_pct_per_hour * elapsed_hours

        # Guard against division by zero and very small expected changes
        if expected_change < MIN_SOC_CHANGE_FOR_LEARNING or expected_change == 0:
            return

        # Calculate observed correction factor
        observed_correction = actual_change / expected_change

        # Clamp to reasonable bounds
        observed_correction = max(
            MIN_CORRECTION_FACTOR,
            min(MAX_CORRECTION_FACTOR, observed_correction),
        )

        # Update learned correction factor with exponential moving average
        self._state.learned_correction_factor = (
            CORRECTION_EMA_ALPHA * observed_correction
            + (1 - CORRECTION_EMA_ALPHA) * self._state.learned_correction_factor
        )

        _LOGGER.debug(
            "Updated correction factor to %.2f for %s (actual: %.1f%%, expected: %.1f%%)",
            self._state.learned_correction_factor,
            self.vehicle.vin,
            actual_change,
            expected_change,
        )

    def _learn_drain_rate(
        self,
        current_soc: float,
        now: datetime,
        was_idle: bool,
    ) -> None:
        """Learn idle drain rate by comparing actual vs predicted SOC changes.

        This helps estimate battery drain when the vehicle is idle (not charging,
        ignition off).
        """
        if self._state.last_actual_soc is None or not was_idle:
            return

        elapsed_hours = self._get_elapsed_hours(now)

        # Need sufficient idle time to learn drain rate accurately
        if elapsed_hours is None or elapsed_hours < MIN_IDLE_TIME_FOR_LEARNING_HOURS:
            return

        actual_change = self._state.last_actual_soc - current_soc  # Drain is positive

        # Only learn from meaningful drain (ignore small fluctuations or gains)
        if actual_change < MIN_SOC_CHANGE_FOR_LEARNING:
            return

        # Calculate observed drain rate
        observed_drain_rate = actual_change / elapsed_hours

        # Clamp to reasonable bounds
        observed_drain_rate = max(
            MIN_IDLE_DRAIN_RATE,
            min(MAX_IDLE_DRAIN_RATE, observed_drain_rate),
        )

        # Update learned drain rate with exponential moving average
        self._state.idle_drain_rate_pct_per_hour = (
            IDLE_DRAIN_EMA_ALPHA * observed_drain_rate
            + (1 - IDLE_DRAIN_EMA_ALPHA) * self._state.idle_drain_rate_pct_per_hour
        )

        _LOGGER.debug(
            "Updated idle drain rate to %.3f%%/h for %s (actual drain: %.1f%% over %.1fh)",
            self._state.idle_drain_rate_pct_per_hour,
            self.vehicle.vin,
            actual_change,
            elapsed_hours,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Available if we have received at least one SOC reading
        return self._state.last_actual_soc is not None

    def _get_elapsed_hours(self, now: datetime) -> float | None:
        """Get hours elapsed since last actual SOC update.

        Returns None if no previous update time is available.
        """
        if self._state.last_actual_soc_time is None:
            return None
        return (now - self._state.last_actual_soc_time).total_seconds() / 3600.0

    def _get_current_vehicle_soc(self) -> float | None:
        """Get current SOC from vehicle, with fallback to stored state."""
        current_soc = getattr(self.vehicle, "state_of_charge", None)
        if current_soc is not None:
            return current_soc
        return self._state.last_actual_soc

    @property
    def native_value(self) -> float | None:
        """Return the extrapolated SOC value."""
        # Always try to get fresh vehicle SOC first
        current_vehicle_soc = self._get_current_vehicle_soc()

        if current_vehicle_soc is None:
            return None

        now = datetime.now(timezone.utc)
        elapsed_hours = self._get_elapsed_hours(now)

        # Guard against missing timestamp or negative elapsed time (clock drift)
        if elapsed_hours is None or elapsed_hours < 0:
            return current_vehicle_soc

        base_soc = self._state.last_actual_soc
        if base_soc is None:
            return current_vehicle_soc

        # Handle idle drain extrapolation (no staleness limit - continue until deep refresh)
        if self._state.is_idle and self._state.idle_drain_rate_pct_per_hour > 0:
            extrapolated = base_soc - (
                self._state.idle_drain_rate_pct_per_hour * elapsed_hours
            )
            # Clamp to valid range (don't go below 0)
            extrapolated = max(0.0, extrapolated)
            return round(extrapolated, 1)

        # Check for staleness - only for charging extrapolation
        if elapsed_hours > STALE_THRESHOLD_HOURS:
            _LOGGER.debug(
                "SOC estimate stale for %s (%.1f hours), returning last accepted SOC",
                self.vehicle.vin,
                elapsed_hours,
            )
            return round(base_soc, 1)

        # If not charging (and not idle), return last accepted SOC
        if not self._state.is_charging or self._state.charging_rate_pct_per_hour <= 0:
            return round(base_soc, 1)

        # If already at or above target, no need to extrapolate charging
        if base_soc >= self._state.target_soc:
            return round(base_soc, 1)

        # Calculate extrapolated SOC for charging
        rate = self._state.charging_rate_pct_per_hour
        correction = self._state.learned_correction_factor

        extrapolated = base_soc + (rate * correction * elapsed_hours)

        # Clamp to target SOC and valid range
        extrapolated = min(extrapolated, self._state.target_soc)
        extrapolated = max(0.0, min(100.0, extrapolated))

        return round(extrapolated, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs = {
            "last_actual_soc": self._state.last_actual_soc,
            "last_update": (
                self._state.last_actual_soc_time.isoformat()
                if self._state.last_actual_soc_time
                else None
            ),
            "is_charging": self._state.is_charging,
            "is_idle": self._state.is_idle,
            "charging_rate_pct_per_hour": round(
                self._state.charging_rate_pct_per_hour, 2
            ),
            "idle_drain_rate_pct_per_hour": round(
                self._state.idle_drain_rate_pct_per_hour, 3
            ),
            "correction_factor": round(self._state.learned_correction_factor, 2),
            "target_soc": self._state.target_soc,
        }
        # Include estimation state for restore
        attrs["estimation_state"] = self._state.to_dict()
        return attrs


class UconnectChargingRateSensor(SensorEntity, UconnectEntity):
    """Sensor showing current charging rate in %/hour."""

    def __init__(
        self,
        coordinator: UconnectDataUpdateCoordinator,
        vehicle: Vehicle,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle)

        self._attr_unique_id = f"{DOMAIN}_{vehicle.vin}_charging_rate"
        self._attr_name = (
            f"{vehicle.make} {vehicle.nickname or vehicle.model} Charging Rate"
        )
        self._attr_native_unit_of_measurement = "%/h"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:battery-charging-high"

    @property
    def native_value(self) -> float | None:
        """Return the charging rate."""
        is_charging = getattr(self.vehicle, "charging", False)
        if not is_charging:
            return 0.0

        current_soc = getattr(self.vehicle, "state_of_charge", None)
        if current_soc is None:
            return None

        charging_level = getattr(self.vehicle, "charging_level", None)
        time_to_full_l2 = getattr(self.vehicle, "time_to_fully_charge_l2", None)
        time_to_full_l3 = getattr(self.vehicle, "time_to_fully_charge_l3", None)

        # Select the appropriate time-to-full based on charging_level
        time_to_full = select_time_to_full(
            charging_level, time_to_full_l2, time_to_full_l3
        )

        if time_to_full is None:
            return None

        rate = calculate_charging_rate(current_soc, time_to_full)
        return round(rate, 1)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return getattr(self.vehicle, "state_of_charge", None) is not None
