"""Extrapolated State of Charge sensor for Uconnect integration.

This sensor predicts the battery charge level even when no data is received
from the vehicle, based on charging status and time-to-full estimates.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from py_uconnect import Vehicle
from py_uconnect.command import COMMAND_DEEP_REFRESH

from .const import DOMAIN
from .coordinator import (
    UconnectCommandTimeout,
    UconnectDataUpdateCoordinator,
    whole_to_int,
)
from .entity import UconnectEntity

_LOGGER = logging.getLogger(__name__)

# Constants for SOC estimation
EXTRAPOLATION_UPDATE_INTERVAL = timedelta(
    minutes=1
)  # Update extrapolated value every minute
DEFAULT_CORRECTION_FACTOR = 1.0  # Default correction factor (no correction)
MIN_CORRECTION_FACTOR = 0.5  # Minimum allowed correction factor
MAX_CORRECTION_FACTOR = 1.5  # Maximum allowed correction factor
CORRECTION_EMA_ALPHA = 0.3  # Exponential moving average factor for correction learning
MIN_TIME_FOR_LEARNING_HOURS = 0.05  # Minimum 3 minutes for learning
MIN_SOC_CHANGE_FOR_LEARNING = 0.5  # Minimum 0.5% SOC change for learning
CHARGING_RATE_WINDOW = timedelta(minutes=60)  # Sliding window for rate computation

# Constants for idle drain estimation
DEFAULT_IDLE_DRAIN_RATE = 0.006  # Default 0.006%/hour ≈ 1%/week ≈ 4%/month
MIN_IDLE_DRAIN_RATE = 0.0  # Minimum drain rate
MAX_IDLE_DRAIN_RATE = 0.04  # Maximum drain rate (0.04%/hour ≈ 1%/day)
MIN_IDLE_TIME_FOR_LEARNING_HOURS = 1.0  # Minimum 1 hour idle for learning drain rate
IDLE_DRAIN_EMA_ALPHA = 0.2  # Slower learning for drain rate (less frequent data points)

# Constants for deep refresh scheduling
# The vehicle settles on a time-to-full for the connected charger only a
# couple of minutes after being plugged in
CHARGE_START_REFRESH_DELAY = timedelta(minutes=3)
# A command the vehicle never answers ties up the status poll for a minute and
# some thirty requests, so stop trying once it is clearly not listening
MAX_DEEP_REFRESH_FAILURES = 3


@dataclass
class SocEstimationState:
    """State for SOC estimation."""

    last_actual_soc: float | None = None
    last_actual_soc_time: datetime | None = None
    last_vehicle_soc: float | None = (
        None  # Raw SOC from vehicle (not adjusted by lock-in)
    )
    last_odometer: float | None = None  # Odometer at the baseline reading
    is_charging: bool = False
    is_idle: bool = False  # Not charging and ignition off
    charging_rate_pct_per_hour: float = 0.0
    has_measured_rate: bool = False  # Stored rate came from observed SOC changes
    measured_this_session: bool = False  # A rate was measured during this charge
    rate_baseline_stale: bool = False  # Baseline reading predates the charge
    idle_drain_rate_pct_per_hour: float = DEFAULT_IDLE_DRAIN_RATE
    learned_correction_factor: float = DEFAULT_CORRECTION_FACTOR
    target_soc: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary for storage."""
        return {
            "last_actual_soc": self.last_actual_soc,
            "last_vehicle_soc": self.last_vehicle_soc,
            "last_odometer": self.last_odometer,
            "last_actual_soc_time": (
                self.last_actual_soc_time.isoformat()
                if self.last_actual_soc_time
                else None
            ),
            "is_charging": self.is_charging,
            "is_idle": self.is_idle,
            "charging_rate_pct_per_hour": self.charging_rate_pct_per_hour,
            "has_measured_rate": self.has_measured_rate,
            "measured_this_session": self.measured_this_session,
            "rate_baseline_stale": self.rate_baseline_stale,
            "idle_drain_rate_pct_per_hour": self.idle_drain_rate_pct_per_hour,
            "learned_correction_factor": self.learned_correction_factor,
            "target_soc": self.target_soc,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SocEstimationState:
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

        # Parse last_vehicle_soc (must be float 0-100 or None)
        last_vehicle_soc = data.get("last_vehicle_soc")
        if last_vehicle_soc is not None and not isinstance(
            last_vehicle_soc, (int, float)
        ):
            last_vehicle_soc = None
        if last_vehicle_soc is not None:
            last_vehicle_soc = max(0.0, min(100.0, last_vehicle_soc))

        # Parse odometer (must be a number or None)
        last_odometer = data.get("last_odometer")
        if not isinstance(last_odometer, (int, float)):
            last_odometer = None

        # Parse timestamp (must be timezone-aware for UTC arithmetic)
        last_time = data.get("last_actual_soc_time")
        last_time_parsed = None
        if isinstance(last_time, str):
            try:
                parsed = datetime.fromisoformat(last_time)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                last_time_parsed = parsed
            except ValueError:
                pass

        # Handle migration from old "learned_efficiency" to new "learned_correction_factor"
        correction = data.get(
            "learned_correction_factor",
            data.get("learned_efficiency", DEFAULT_CORRECTION_FACTOR),
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
        if (
            not isinstance(target_soc, (int, float))
            or target_soc <= 0
            or target_soc > 100
        ):
            target_soc = 100.0

        # Whole values as int, the vehicle reports them like that and they
        # are shown as is when not extrapolating (see whole_to_int)
        return cls(
            last_actual_soc=(
                whole_to_int(float(last_soc)) if last_soc is not None else None
            ),
            last_actual_soc_time=last_time_parsed,
            last_vehicle_soc=(
                whole_to_int(float(last_vehicle_soc))
                if last_vehicle_soc is not None
                else None
            ),
            last_odometer=(float(last_odometer) if last_odometer is not None else None),
            is_charging=bool(data.get("is_charging", False)),
            is_idle=bool(data.get("is_idle", False)),
            charging_rate_pct_per_hour=float(charging_rate),
            has_measured_rate=bool(data.get("has_measured_rate", False)),
            measured_this_session=bool(
                data.get("measured_this_session", data.get("has_measured_rate", False))
            ),
            rate_baseline_stale=bool(data.get("rate_baseline_stale", False)),
            idle_drain_rate_pct_per_hour=float(drain_rate),
            learned_correction_factor=float(correction),
            target_soc=float(target_soc),
        )


def select_time_to_full(
    charging_level: int | None,
    time_l1: float | None,
    time_l2: float | None,
    time_l3: float | None,
) -> float | None:
    """Select the appropriate time-to-full value based on charging_level.

    The library reports the level as an integer: 1 for a domestic socket, 2
    for AC and 3 for DC. A level names the charger that is connected, so when
    it does and that charger has published nothing usable the answer is
    nothing: substituting another one can be an order of magnitude out, a
    domestic socket reading as DC being the case that prompted this. Only an
    unknown level falls back to the shortest value on offer, that being the
    most likely active charger. The library reports 0 for DEFAULT, which names
    no charger and so takes the fallback like a missing level does.
    """
    times: dict[int, float | None] = {1: time_l1, 2: time_l2, 3: time_l3}

    if charging_level in times:
        selected = times[charging_level]
        return selected if selected is not None and selected > 0 else None

    valid = [t for t in times.values() if t is not None and t > 0]
    return min(valid) if valid else None


def vehicle_time_to_full(vehicle: Vehicle) -> float | None:
    """Return the time-to-full for the charger the vehicle reports."""
    return select_time_to_full(
        getattr(vehicle, "charging_level", None),
        getattr(vehicle, "time_to_fully_charge_l1", None),
        getattr(vehicle, "time_to_fully_charge_l2", None),
        getattr(vehicle, "time_to_fully_charge_l3", None),
    )


def calculate_charging_rate(
    current_soc: float,
    time_to_full_minutes: float | None,
) -> float:
    """Calculate initial charging rate estimate in percentage per hour.

    Used as a fallback when no observed rate from consecutive SOC readings
    is available (e.g., at the start of a charging session).

    Note: This computes the average rate over the remaining charge time
    (current SOC to 100%), which underestimates the instantaneous rate
    during the CC (constant current) phase since the average includes
    the slower CV taper phase.
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
            f"{vehicle.make} {vehicle.nickname or vehicle.model} Extrapolated Battery"
        )
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:battery-sync"

        self._state = SocEstimationState()
        self._unsub_timer: Callable[[], None] | None = None
        self._unsub_deep_refresh: Callable[[], None] | None = None
        self._deep_refresh_failures: int = 0

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
                    _LOGGER.warning("Failed to restore SOC estimation state: %s", err)

        # Initialize with current vehicle state
        self._update_from_vehicle()

        # Resume the deep refresh schedule when Home Assistant restarts during
        # a charge, the charging state carries over so no transition is seen
        if self._state.is_charging:
            self._schedule_deep_refresh(CHARGE_START_REFRESH_DELAY)

        # Set up periodic timer for extrapolation updates
        self._unsub_timer = async_track_time_interval(
            self.hass,
            self._async_update_extrapolation,
            EXTRAPOLATION_UPDATE_INTERVAL,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up timers when entity is removed."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        self._cancel_deep_refresh()
        # Disabling the entity leaves the config entry loaded, so drop the
        # registration too or the coordinator keeps handing work to an entity
        # that is no longer part of Home Assistant
        self.coordinator.extrapolated_soc_sensors.pop(self._vin, None)
        await super().async_will_remove_from_hass()

    @callback
    def reset_learning(self) -> None:
        """Reset the learned values, including the carried charging rate.

        The rate is kept across sessions so the next one can extrapolate from
        the first minute, which is exactly wrong after a charger swap, and
        this button is what a user reaches for then. Clearing it sends the
        next session back to the vehicle's own time-to-full.
        """
        self._state.learned_correction_factor = DEFAULT_CORRECTION_FACTOR
        self._state.idle_drain_rate_pct_per_hour = DEFAULT_IDLE_DRAIN_RATE
        self._state.charging_rate_pct_per_hour = 0.0
        self._state.has_measured_rate = False
        self._state.measured_this_session = False
        self.async_write_ha_state()

    @callback
    def _async_update_extrapolation(self, _now: datetime) -> None:
        """Periodically update the extrapolated value."""
        # Update if charging or idle (both need extrapolation)
        if (self._state.is_charging and self._state.charging_rate_pct_per_hour > 0) or (
            self._state.is_idle and self._state.idle_drain_rate_pct_per_hour > 0
        ):
            self.async_write_ha_state()

    async def _async_do_deep_refresh(self) -> None:
        """Ask the vehicle to push fresh data."""
        _LOGGER.info("Triggering deep refresh for %s", self._vin)
        try:
            await self.coordinator.async_command(self._vin, COMMAND_DEEP_REFRESH)
            self._deep_refresh_failures = 0
        except Exception as err:
            self._deep_refresh_failures += 1
            _LOGGER.warning(
                "Deep refresh failed for %s (%d/%d): %s",
                self._vin,
                self._deep_refresh_failures,
                MAX_DEEP_REFRESH_FAILURES,
                err,
            )
            # A refusal is still an answer, and a command the vehicle
            # answered has already been followed by a read. Only one left
            # unanswered needs another: the status poll gives up after a
            # minute, which the vehicle can outlast, so a slow but successful
            # refresh would be wasted
            if isinstance(err, UconnectCommandTimeout) or not isinstance(
                err, HomeAssistantError
            ):
                await self.coordinator.async_request_refresh()

    def _can_deep_refresh(self) -> bool:
        """Check whether an automatic deep refresh can reach the vehicle.

        The command is authenticated with the PIN, which is optional, and is
        not offered by every vehicle. Every other caller checks this, so
        without it a charge on an unsupported account queues a command that
        can only fail.
        """

        if not self.coordinator.client.api.pin:
            return False

        vehicle = self.coordinator.client.get_vehicles().get(self._vin)
        if vehicle is None:
            return False

        return COMMAND_DEEP_REFRESH.name in vehicle.supported_commands

    @callback
    def _cancel_deep_refresh(self) -> None:
        """Cancel a pending deep refresh."""
        if self._unsub_deep_refresh:
            self._unsub_deep_refresh()
            self._unsub_deep_refresh = None

    @callback
    def _schedule_deep_refresh(self, delay: timedelta) -> None:
        """Schedule a deep refresh after the given delay."""

        if not self._can_deep_refresh():
            return

        @callback
        def _fire(_now: datetime) -> None:
            self._unsub_deep_refresh = None
            if not self._state.is_charging:
                return
            if self._deep_refresh_failures >= MAX_DEEP_REFRESH_FAILURES:
                _LOGGER.warning(
                    "Giving up on deep refresh for %s after %d consecutive "
                    "failures, will try again on the next charging session",
                    self._vin,
                    self._deep_refresh_failures,
                )
                return
            interval = self.coordinator.charging_refresh_interval
            if interval:
                self._schedule_deep_refresh(timedelta(minutes=interval))
            self.hass.async_create_task(self._async_do_deep_refresh())

        self._cancel_deep_refresh()
        self._unsub_deep_refresh = async_call_later(self.hass, delay, _fire)

    @callback
    def resume_deep_refresh(self) -> None:
        """Pick the deep refresh back up after the options changed.

        The schedule keeps itself alive from one refresh to the next, so a
        charge that started with the interval disabled, or without a PIN to
        authenticate the command, has nothing left to re-arm it and would
        otherwise wait for the next session.
        """

        if (
            self._state.is_charging
            and self._unsub_deep_refresh is None
            and self.coordinator.charging_refresh_interval
        ):
            # The options may be what the refreshes were failing over, a PIN
            # the vehicle rejected being the obvious one, so the count of
            # earlier failures should not bar the retry
            self._deep_refresh_failures = 0
            self._schedule_deep_refresh(
                timedelta(minutes=self.coordinator.charging_refresh_interval)
            )

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
        time_to_full = vehicle_time_to_full(self.vehicle)

        now = datetime.now(UTC)

        # Track if we're skipping due to stale charging data
        skip_stale_charging_data = False
        soc_changed = False

        if current_soc is not None:
            # Only update baseline if SOC actually changed
            # This preserves extrapolation continuity across HA restarts
            soc_changed = (
                self._state.last_vehicle_soc is None
                or current_soc != self._state.last_vehicle_soc
            )

            # Only update SOC when charging/driving and new value exceeds extrapolated
            # When idle (parked), car data is stale and shouldn't reset extrapolation
            # Only skip if car WAS idle AND IS STILL idle - any state transition
            # (idle→driving or driving→idle) means fresh data
            current_extrapolated = self.native_value
            is_idle = not is_charging and not ignition_on

            # Physical constraint: SOC cannot drop while already charging
            # Requires the stored state (was already charging) so that
            # idle→charging transitions with lower SOC from idle drain are
            # accepted, and the reported state (still charging) so that a drop
            # after the charger was unplugged is not rejected forever
            if (
                soc_changed
                and self._state.is_charging  # Was already charging
                and is_charging  # And still is
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
                if (
                    current_extrapolated is not None
                    and current_soc <= current_extrapolated
                ):
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

        # Save previous state for learning and rate calculation
        was_charging = self._state.is_charging
        was_idle = self._state.is_idle
        prev_soc = self._state.last_actual_soc
        prev_soc_time = self._state.last_actual_soc_time

        # Update charging and idle state (unless we detected stale charging data)
        # Skip when current_soc is None to preserve restored state after reboot
        if current_soc is not None and not skip_stale_charging_data:
            self._state.is_charging = is_charging
            self._state.is_idle = not is_charging and not ignition_on

        # Learn from readings the vehicle actually published, which a deep
        # refresh makes sure of. A reading either guard rejected is stale by
        # definition, and it is also never consumed: the baseline does not
        # move, so the same one would be relearned on every poll until the
        # extrapolation happens to catch up with it, driving an average that
        # is meant to be slow straight to whatever that single sample says
        if (
            current_soc is not None
            and self._state.last_actual_soc is not None
            and soc_changed
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
            self._state.last_vehicle_soc = current_soc
            self._state.last_odometer = getattr(self.vehicle, "odometer", None)

        # When transitioning from idle to non-idle (car powers on) without
        # fresh SOC data, lock in the accumulated idle drain so native_value
        # doesn't jump back up to the pre-drain baseline
        if was_idle and not self._state.is_idle and not soc_changed:
            elapsed_hours = self._get_elapsed_hours(now)
            if (
                elapsed_hours is not None
                and elapsed_hours > 0
                and self._state.last_actual_soc is not None
            ):
                drain = self._state.idle_drain_rate_pct_per_hour * elapsed_hours
                if drain > 0:
                    old_soc = self._state.last_actual_soc
                    self._state.last_actual_soc = max(
                        0.0, self._state.last_actual_soc - drain
                    )
                    self._state.last_actual_soc_time = now
                    _LOGGER.debug(
                        "Locked in idle drain for %s: adjusted SOC %.1f%% -> %.1f%% "
                        "(%.3f%% over %.1fh)",
                        self.vehicle.vin,
                        old_soc,
                        self._state.last_actual_soc,
                        drain,
                        elapsed_hours,
                    )

        # Restart the measurement window when charging starts, so the first
        # observed rate is not diluted by the time that passed before the car
        # was plugged in. Driving to charging leaves the baseline stamped at
        # the last reading of the drive, which can be well over an hour old
        if (
            self._state.is_charging
            and not was_charging
            and self._state.last_actual_soc is not None
        ):
            # Only the time moves, so the state of charge paired with it can
            # be older than the timestamp now says. Coming from idle that is
            # harmless, the reading did not move because the car was parked
            # and the drain lock-in above has already reconciled the pair.
            # Coming from a drive it is not: the gain since that reading would
            # all be credited to the short window after the restamp, so wait
            # for a reading taken while charging before measuring
            self._state.rate_baseline_stale = not soc_changed and not was_idle
            self._state.last_actual_soc_time = now

        # Calculate charging rate if charging with valid data
        # Don't recalculate if we detected stale charging data
        # Skip when current_soc is None to preserve restored rate after reboot
        if current_soc is not None and not skip_stale_charging_data:
            if is_charging:
                # Prefer observed rate from consecutive SOC readings.
                # Require MIN_SOC_CHANGE_FOR_LEARNING to filter out tiny deltas
                # from idle drain lock-in adjustments.
                if (
                    was_charging
                    and soc_changed
                    and not self._state.rate_baseline_stale
                    and prev_soc is not None
                    and prev_soc_time is not None
                    and current_soc - prev_soc >= MIN_SOC_CHANGE_FOR_LEARNING
                ):
                    elapsed = (now - prev_soc_time).total_seconds() / 3600.0
                    if elapsed >= MIN_TIME_FOR_LEARNING_HOURS:
                        self._state.charging_rate_pct_per_hour = min(
                            (current_soc - prev_soc) / elapsed, 300.0
                        )
                        self._state.has_measured_rate = True
                        self._state.measured_this_session = True
                elif not self._state.measured_this_session and time_to_full is not None:
                    # Track the time-to-full estimate until an observed rate is
                    # available. This also overrides any stale rate carried
                    # over from a previous session. The value the vehicle
                    # reports at plug-in is often a placeholder, so keep taking
                    # the latest one rather than locking in the first.
                    # Only accept a positive rate so that a zero return
                    # (e.g. time_to_full < 1 min) does not discard a usable
                    # stale fallback.
                    rate = calculate_charging_rate(current_soc, time_to_full)
                    if rate > 0:
                        self._state.charging_rate_pct_per_hour = rate
                        self._state.has_measured_rate = False

                # This reading was taken while charging, so it can be timed and
                # the next one measures a rate from it
                if soc_changed:
                    self._state.rate_baseline_stale = False
            else:
                # Reset the flag so the next charging session can pick up a
                # fresh time-to-full estimate. The rate itself is preserved
                # as a fallback for the next session, and stays marked with
                # where it came from so a carried over measurement is not
                # mistaken for an estimate and corrected
                self._state.measured_this_session = False

        # Default target SOC to 100% (no target SOC limit for this vehicle type)
        self._state.target_soc = 100.0

        # Deep refresh a few minutes after charging starts, once the vehicle
        # has settled on a time-to-full for the connected charger. Refreshing
        # at the very moment the charging flag appears returns the estimate
        # the vehicle held before the charger was negotiated
        if self._state.is_charging and not was_charging:
            self._deep_refresh_failures = 0
            self._schedule_deep_refresh(CHARGE_START_REFRESH_DELAY)
        elif was_charging and not self._state.is_charging:
            self._cancel_deep_refresh()

    def _learn_correction_factor(
        self,
        current_soc: float,
        now: datetime,
        was_charging: bool,
    ) -> None:
        """Learn a correction factor by comparing actual vs predicted SOC changes.

        This helps account for discrepancies between the vehicle's time-to-full
        estimate and actual charging behavior. It only applies while the rate
        comes from that estimate, learning it from a measured rate would drive
        it towards 1.0 and leave nothing to correct the next estimate with.

        A baseline restamped at charging start is skipped for the same reason
        the rate measurement skips it: the change since the stored reading did
        not all happen inside the window the timestamp describes.
        """
        if (
            self._state.last_actual_soc is None
            or not was_charging
            or self._state.rate_baseline_stale
            or self._state.has_measured_rate
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
        ignition off). The vehicle has to be idle at both ends of the window,
        since one that has since been driven spent the drop on moving, not on
        sitting still, and a single drive reads as hundreds of times the drain
        a parked car has.
        """
        if (
            self._state.last_actual_soc is None
            or not was_idle
            or not self._state.is_idle
        ):
            return

        # Idle at both ends still leaves room for a drive in between when the
        # vehicle went quiet for a while, and the odometer is the only thing
        # that can tell. A vehicle that does not report one keeps the weaker
        # test rather than never learning a drain rate at all
        odometer = getattr(self.vehicle, "odometer", None)
        if (
            odometer is not None
            and self._state.last_odometer is not None
            and odometer != self._state.last_odometer
        ):
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

        now = datetime.now(UTC)
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

        # If not charging (and not idle), return last accepted SOC
        if not self._state.is_charging or self._state.charging_rate_pct_per_hour <= 0:
            return round(base_soc, 1)

        # If already at or above target, no need to extrapolate charging
        if base_soc >= self._state.target_soc:
            return round(base_soc, 1)

        # Calculate extrapolated SOC for charging. The correction factor
        # accounts for the vehicle's time-to-full being optimistic or
        # pessimistic, so it has nothing to correct on a measured rate
        rate = self._state.charging_rate_pct_per_hour
        correction = (
            1.0
            if self._state.has_measured_rate
            else self._state.learned_correction_factor
        )

        extrapolated = base_soc + (rate * correction * elapsed_hours)

        # Clamp to target SOC and valid range
        extrapolated = min(extrapolated, self._state.target_soc)
        extrapolated = max(0.0, min(100.0, extrapolated))

        return round(extrapolated, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {
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

        self._soc_history: deque[tuple[datetime, float]] = deque()
        self._observed_rate: float | None = None
        self._observed_rate_time: datetime | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Track SOC changes to compute observed charging rate."""
        is_charging = getattr(self.vehicle, "charging", False) or False
        current_soc = getattr(self.vehicle, "state_of_charge", None)

        if not is_charging or current_soc is None:
            self._soc_history.clear()
            self._observed_rate = None
            self._observed_rate_time = None
            self.async_write_ha_state()
            return

        now = datetime.now(UTC)
        self._soc_history.append((now, current_soc))

        # Trim entries outside the sliding window
        cutoff = now - CHARGING_RATE_WINDOW
        while self._soc_history and self._soc_history[0][0] < cutoff:
            self._soc_history.popleft()

        # Compute rate across the window span
        if len(self._soc_history) >= 2:
            oldest_time, oldest_soc = self._soc_history[0]
            elapsed_hours = (now - oldest_time).total_seconds() / 3600.0
            delta = current_soc - oldest_soc
            # A flat window means the API has not given us a new reading yet,
            # not that charging has stopped. Publishing the 0%/h it computes
            # would also suppress the time-to-full fallback below
            if elapsed_hours >= MIN_TIME_FOR_LEARNING_HOURS and delta > 0:
                self._observed_rate = min(delta / elapsed_hours, 300.0)
                self._observed_rate_time = now

        self.async_write_ha_state()

    @property
    def _measurement_is_current(self) -> bool:
        """Whether the observed rate still describes the window it was taken over.

        Past that it says nothing about the charge now, and a session held at
        its target would keep reporting the speed it last reached.
        """

        if self._observed_rate is None or self._observed_rate_time is None:
            return False

        age = datetime.now(UTC) - self._observed_rate_time
        return age <= CHARGING_RATE_WINDOW

    @property
    def native_value(self) -> float | None:
        """Return the charging rate."""
        is_charging = getattr(self.vehicle, "charging", False)
        if not is_charging:
            return 0.0

        # Prefer observed rate from actual SOC changes
        if self._measurement_is_current:
            return round(self._observed_rate, 1)

        # Fall back to time-to-full estimate for initial reading, and again
        # once the last measurement has aged out
        current_soc = getattr(self.vehicle, "state_of_charge", None)
        time_to_full = vehicle_time_to_full(self.vehicle)

        if current_soc is not None and time_to_full is not None:
            return round(calculate_charging_rate(current_soc, time_to_full), 1)

        # Nothing current on offer. An aged measurement still beats going
        # unknown, which is what the vehicle leaves us with when it publishes
        # neither a new state of charge nor a time-to-full
        if self._observed_rate is not None:
            return round(self._observed_rate, 1)

        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return getattr(self.vehicle, "state_of_charge", None) is not None
