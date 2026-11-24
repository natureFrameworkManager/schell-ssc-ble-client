"""Presence state machine for dynamically discovered devices."""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from typing import Any

import simplepyble

from ssc.db.models import Device
from ssc.db.repository import Repository
from ssc.recorder.config import RecorderConfig

logger = logging.getLogger(__name__)


def _json_default(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    return str(value)


@dataclass(slots=True)
class DiscoveredDevice:
    address: str
    peripheral: simplepyble.Peripheral
    advertisement: dict[str, Any] | None
    rssi: int | None
    serial: str | None
    display_name: str | None
    product: str | None
    battery_voltage_adv: int | None
    battery_level: int | None


@dataclass(slots=True)
class DeviceRuntime:
    device_id: int
    address: str
    online_period_id: int | None = None
    last_seen_at: dt.datetime | None = None
    misses: int = 0
    query_attempts: int = 0
    query_status: str = "pending"
    last_query_at: dt.datetime | None = None


class PresenceTracker:
    """Owns the online/off period transitions for every discovered device."""

    def __init__(
        self,
        repository: Repository,
        config: RecorderConfig,
        run_id: int | None,
    ) -> None:
        self.repository = repository
        self.config = config
        self.run_id = run_id
        self.runtimes: dict[int, DeviceRuntime] = {}
        self.by_address: dict[str, DeviceRuntime] = {}

    def load(self) -> None:
        """Load all devices persisted by earlier runs."""
        for device in self.repository.list_devices():
            runtime = self._runtime_from_device(device)
            self._register(runtime)

    def _runtime_from_device(self, device: Device) -> DeviceRuntime:
        open_online = self.repository.get_open_online_period(device.id)  # type: ignore[arg-type]
        return DeviceRuntime(
            device_id=device.id,  # type: ignore[arg-type]
            address=device.address,
            online_period_id=open_online.id if open_online else None,
            last_seen_at=open_online.last_seen_at if open_online else device.last_seen_at,
        )

    def _register(self, runtime: DeviceRuntime) -> None:
        self.runtimes[runtime.device_id] = runtime
        self.by_address[runtime.address] = runtime

    def get_or_create(
        self, discovered: DiscoveredDevice, now: dt.datetime
    ) -> DeviceRuntime:
        runtime = self.by_address.get(discovered.address)
        if runtime is not None:
            self.repository.update_device_seen(runtime.device_id, now)
            return runtime

        device = self.repository.get_or_create_device(
            discovered.address,
            identifier=discovered.peripheral.identifier(),
            serial=discovered.serial,
            display_name=discovered.display_name,
            product=discovered.product,
            seen_at=now,
        )
        runtime = self._runtime_from_device(device)
        self._register(runtime)
        logger.info(
            "Discovered new SSC device %s (%s)",
            discovered.address,
            discovered.display_name or discovered.serial or "unnamed",
        )
        return runtime

    def observe(self, discovered: DiscoveredDevice, now: dt.datetime) -> bool:
        """Record a found scan and return whether a state query is due."""
        runtime = self.get_or_create(discovered, now)
        advertisement_json = (
            json.dumps(discovered.advertisement, sort_keys=True, default=_json_default)
            if discovered.advertisement is not None
            else None
        )

        if runtime.online_period_id is None:
            online = self.repository.open_online_period(
                runtime.device_id, self.run_id, now
            )
            assert online.id is not None
            runtime.online_period_id = online.id
            runtime.last_seen_at = now
            runtime.misses = 0
            runtime.query_attempts = 0
            runtime.query_status = "pending"

            open_off = self.repository.get_open_off_period(runtime.device_id)
            if open_off is not None and open_off.id is not None:
                self.repository.close_off_period(
                    open_off.id,
                    ended_at=now,
                    next_online_period_id=online.id,
                )

            self.repository.insert_presence_sample(
                online_period_id=online.id,
                device_id=runtime.device_id,
                observed_at=now,
                rssi=discovered.rssi,
                battery_voltage_adv=discovered.battery_voltage_adv,
                battery_level=discovered.battery_level,
                advertisement_json=advertisement_json,
            )
            logger.info(
                "Device %s is online; starting state query",
                discovered.address,
            )
            return True

        self.repository.touch_online_period(runtime.online_period_id, now)
        runtime.last_seen_at = now
        runtime.misses = 0

        if self.config.presence_sample_mode == "every_scan":
            self.repository.insert_presence_sample(
                online_period_id=runtime.online_period_id,
                device_id=runtime.device_id,
                observed_at=now,
                rssi=discovered.rssi,
                battery_voltage_adv=discovered.battery_voltage_adv,
                battery_level=discovered.battery_level,
                advertisement_json=None,
            )

        if (
            self.config.requery_interval_s > 0
            and runtime.last_query_at is not None
            and (now - runtime.last_query_at).total_seconds()
            >= self.config.requery_interval_s
        ):
            runtime.query_status = "pending"

        return (
            runtime.query_status in {"pending", "retry"}
            and runtime.query_attempts < self.config.max_query_attempts
        )

    def miss(self, runtime: DeviceRuntime, now: dt.datetime) -> None:
        """Record a scan in which the device was absent."""
        if runtime.online_period_id is None:
            return

        runtime.misses += 1
        if runtime.misses < self.config.offline_after_misses:
            return

        ended_at = runtime.last_seen_at or now
        self.repository.close_online_period(
            runtime.online_period_id,
            ended_at=ended_at,
            detected_at=now,
            reason="scans_missed",
        )
        self.repository.open_off_period(
            runtime.device_id,
            started_at=ended_at,
            previous_online_period_id=runtime.online_period_id,
            start_accuracy="last_seen_estimate",
            fully_observed=True,
        )
        logger.info(
            "Device %s is offline after %s missed scans",
            runtime.address,
            runtime.misses,
        )
        runtime.online_period_id = None
        runtime.misses = 0
        runtime.query_status = "pending"
        runtime.query_attempts = 0

    def query_succeeded(self, runtime: DeviceRuntime, now: dt.datetime) -> None:
        runtime.query_status = "done"
        runtime.last_query_at = now

    def query_failed(
        self,
        runtime: DeviceRuntime,
        now: dt.datetime,
        *,
        error: str,
    ) -> str:
        runtime.query_attempts += 1
        runtime.last_query_at = now
        if runtime.query_attempts >= self.config.max_query_attempts:
            runtime.query_status = "failed"
            logger.error(
                "Giving up querying %s after %s attempts: %s",
                runtime.address,
                runtime.query_attempts,
                error,
            )
        else:
            runtime.query_status = "retry"
            logger.warning(
                "Querying %s failed (attempt %s/%s): %s",
                runtime.address,
                runtime.query_attempts,
                self.config.max_query_attempts,
                error,
            )
        return runtime.query_status

    def close_all(self, now: dt.datetime, reason: str) -> None:
        """Close open online periods when the recorder stops."""
        for runtime in self.runtimes.values():
            if runtime.online_period_id is None:
                continue
            ended_at = runtime.last_seen_at or now
            self.repository.close_online_period(
                runtime.online_period_id,
                ended_at=ended_at,
                detected_at=now,
                reason=reason,
            )
            self.repository.open_off_period(
                runtime.device_id,
                started_at=ended_at,
                previous_online_period_id=runtime.online_period_id,
                start_accuracy="last_seen_estimate",
                fully_observed=False,
            )
            runtime.online_period_id = None