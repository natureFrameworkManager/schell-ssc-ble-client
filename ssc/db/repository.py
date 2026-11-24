"""Repository helpers for the recorder database.

The repository is the only place that writes rows.  It keeps state-machine
transitions and snapshot writes transactional while exposing small methods to
the recorder runner.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import zlib
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from ssc.db.models import (
    CalendarSlot,
    ConfigChange,
    ConfigFieldValue,
    DailyStat,
    Device,
    EepromImage,
    EventLogEntry,
    FirmwareState,
    LifetimeStatsState,
    ModuleInfoState,
    OffPeriod,
    OnlinePeriod,
    PresenceSample,
    RecorderRun,
    ScanRun,
    StateSnapshot,
    TelemetryState,
    TodayStatsState,
    utcnow,
)
from ssc.eeprom.layout import FIELDS

logger = logging.getLogger(__name__)

SECRET_FIELD_NAMES = frozenset({"EEPROM_DevicePassword", "EEPROM_Password"})


def _json_default(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    return str(value)


def _json_text(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=_json_default)


def _sha256_text(value: object) -> str:
    return hashlib.sha256(_json_text(value).encode("utf-8")).hexdigest()


def _seconds_between(start: dt.datetime, end: dt.datetime) -> int:
    return max(0, int((end - start).total_seconds()))


class Repository:
    """Small transaction-oriented API around the SQLite database."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # -- runs ---------------------------------------------------------------

    def start_run(self, host: str | None, version: str | None) -> RecorderRun:
        """Close stale runs and start a new one."""
        now = utcnow()
        with Session(self.engine) as session:
            stale = session.exec(
                select(RecorderRun).where(RecorderRun.stopped_at.is_(None))
            ).all()
            for run in stale:
                run.stopped_at = now
                run.stop_reason = "recorder_restart"
                session.add(run)

            run = RecorderRun(started_at=now, host=host, version=version)
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

    def finish_run(self, run_id: int, reason: str) -> None:
        with Session(self.engine) as session:
            run = session.get(RecorderRun, run_id)
            if run is not None and run.stopped_at is None:
                run.stopped_at = utcnow()
                run.stop_reason = reason
                session.add(run)
                session.commit()

    # -- devices ------------------------------------------------------------

    def list_devices(self) -> list[Device]:
        with Session(self.engine) as session:
            return list(session.exec(select(Device).order_by(Device.id)).all())

    def get_device(self, device_id: int) -> Device | None:
        with Session(self.engine) as session:
            return session.get(Device, device_id)

    def get_or_create_device(
        self,
        address: str,
        *,
        identifier: str = "",
        serial: str | None = None,
        display_name: str | None = None,
        product: str | None = None,
        seen_at: dt.datetime | None = None,
    ) -> Device:
        """Return the device for *address*, creating/updating it as needed."""
        seen_at = seen_at or utcnow()
        with Session(self.engine) as session:
            device = session.exec(
                select(Device).where(Device.address == address)
            ).first()
            if device is None:
                device = Device(
                    address=address,
                    identifier=identifier,
                    serial=serial,
                    display_name=display_name,
                    product=product,
                    first_seen_at=seen_at,
                    last_seen_at=seen_at,
                )
                session.add(device)
            else:
                if identifier:
                    device.identifier = identifier
                if serial:
                    device.serial = serial
                if display_name:
                    device.display_name = display_name
                if product:
                    device.product = product
                device.last_seen_at = seen_at
                session.add(device)
            session.commit()
            session.refresh(device)
            return device

    def update_device_seen(self, device_id: int, seen_at: dt.datetime) -> None:
        with Session(self.engine) as session:
            device = session.get(Device, device_id)
            if device is None:
                return
            device.last_seen_at = seen_at
            session.add(device)
            session.commit()

    # -- presence periods ---------------------------------------------------

    def get_open_online_period(self, device_id: int) -> OnlinePeriod | None:
        with Session(self.engine) as session:
            return session.exec(
                select(OnlinePeriod)
                .where(OnlinePeriod.device_id == device_id)
                .where(OnlinePeriod.ended_at.is_(None))
                .order_by(OnlinePeriod.started_at.desc())
            ).first()

    def get_open_off_period(self, device_id: int) -> OffPeriod | None:
        with Session(self.engine) as session:
            return session.exec(
                select(OffPeriod)
                .where(OffPeriod.device_id == device_id)
                .where(OffPeriod.ended_at.is_(None))
                .order_by(OffPeriod.started_at.desc())
            ).first()

    def open_online_period(
        self,
        device_id: int,
        run_id: int | None,
        started_at: dt.datetime,
    ) -> OnlinePeriod:
        with Session(self.engine) as session:
            period = OnlinePeriod(
                device_id=device_id,
                recorder_run_id=run_id,
                started_at=started_at,
                last_seen_at=started_at,
                scan_count=1,
                query_status="pending",
            )
            session.add(period)
            session.commit()
            session.refresh(period)
            return period

    def touch_online_period(self, period_id: int, observed_at: dt.datetime) -> None:
        with Session(self.engine) as session:
            period = session.get(OnlinePeriod, period_id)
            if period is None or period.ended_at is not None:
                return
            period.last_seen_at = observed_at
            period.scan_count += 1
            session.add(period)
            session.commit()

    def close_online_period(
        self,
        period_id: int,
        *,
        ended_at: dt.datetime,
        detected_at: dt.datetime | None,
        reason: str,
    ) -> None:
        with Session(self.engine) as session:
            period = session.get(OnlinePeriod, period_id)
            if period is None or period.ended_at is not None:
                return
            period.ended_at = ended_at
            period.offline_detected_at = detected_at
            period.ended_reason = reason
            period.duration_s = _seconds_between(period.started_at, ended_at)
            session.add(period)
            session.commit()

    def open_off_period(
        self,
        device_id: int,
        *,
        started_at: dt.datetime,
        previous_online_period_id: int | None,
        start_accuracy: str = "observed",
        fully_observed: bool = True,
    ) -> OffPeriod:
        with Session(self.engine) as session:
            period = OffPeriod(
                device_id=device_id,
                previous_online_period_id=previous_online_period_id,
                started_at=started_at,
                start_accuracy=start_accuracy,
                fully_observed=fully_observed,
            )
            session.add(period)
            session.commit()
            session.refresh(period)
            return period

    def close_off_period(
        self,
        period_id: int,
        *,
        ended_at: dt.datetime,
        next_online_period_id: int | None,
    ) -> None:
        with Session(self.engine) as session:
            period = session.get(OffPeriod, period_id)
            if period is None or period.ended_at is not None:
                return
            period.ended_at = ended_at
            period.next_online_period_id = next_online_period_id
            period.duration_s = _seconds_between(period.started_at, ended_at)
            session.add(period)
            session.commit()

    def mark_open_off_period_unobserved(self, device_id: int) -> bool:
        """Mark an existing open off period as interrupted by a restart."""
        with Session(self.engine) as session:
            period = session.exec(
                select(OffPeriod)
                .where(OffPeriod.device_id == device_id)
                .where(OffPeriod.ended_at.is_(None))
                .order_by(OffPeriod.started_at.desc())
            ).first()
            if period is None:
                return False
            period.fully_observed = False
            session.add(period)
            session.commit()
            return True

    def insert_presence_sample(
        self,
        *,
        online_period_id: int,
        device_id: int,
        observed_at: dt.datetime,
        rssi: int | None,
        battery_voltage_adv: int | None,
        battery_level: int | None,
        advertisement_json: str | None = None,
    ) -> bool:
        """Insert one found-scan row; return False if it already exists."""
        with Session(self.engine) as session:
            existing = session.get(PresenceSample, (online_period_id, observed_at))
            if existing is not None:
                return False
            session.add(
                PresenceSample(
                    online_period_id=online_period_id,
                    observed_at=observed_at,
                    device_id=device_id,
                    rssi=rssi,
                    battery_voltage_adv=battery_voltage_adv,
                    battery_level=battery_level,
                    advertisement_json=advertisement_json,
                )
            )
            session.commit()
            return True

    def update_online_query(
        self,
        period_id: int,
        *,
        status: str,
        attempts: int,
        queried_at: dt.datetime | None = None,
    ) -> None:
        with Session(self.engine) as session:
            period = session.get(OnlinePeriod, period_id)
            if period is None:
                return
            period.query_status = status
            period.query_attempts = attempts
            if queried_at is not None:
                period.queried_at = queried_at
            session.add(period)
            session.commit()

    # -- snapshots ----------------------------------------------------------

    def save_snapshot(
        self,
        *,
        device_id: int,
        online_period_id: int | None,
        captured_at: dt.datetime,
        completed_at: dt.datetime | None,
        image: bytes | None,
        start_address: int,
        coverage: int,
        missing_ranges: list[list[int]] | None,
        parsed: dict[str, Any],
        query_status: str,
        error: str | None,
        redact_secrets: bool,
    ) -> int:
        """Persist one complete query result in a single transaction."""
        with Session(self.engine) as session:
            eeprom_image_id: int | None = None
            if image is not None:
                stored = _ensure_eeprom_image(
                    session,
                    image,
                    captured_at=captured_at,
                    start_address=start_address,
                    coverage=coverage,
                )
                eeprom_image_id = stored.id

            snapshot = StateSnapshot(
                device_id=device_id,
                online_period_id=online_period_id,
                eeprom_image_id=eeprom_image_id,
                captured_at=captured_at,
                completed_at=completed_at,
                device_datetime=parsed.get("device_datetime"),  # type: ignore[arg-type]
                query_status=query_status,
                coverage=coverage,
                missing_ranges=missing_ranges,
                error=error,
            )
            session.add(snapshot)
            session.flush()
            snapshot_id = snapshot.id
            assert snapshot_id is not None

            telemetry = parsed.get("telemetry")
            if isinstance(telemetry, dict):
                battery = telemetry.get("battery")
                battery = battery if isinstance(battery, dict) else {}
                session.add(
                    TelemetryState(
                        snapshot_id=snapshot_id,
                        captured_at=captured_at,
                        temperature_raw=telemetry.get("temperature"),  # type: ignore[arg-type]
                        battery_voltage_raw=telemetry.get("battery_voltage_raw"),  # type: ignore[arg-type]
                        battery_voltage_v=battery.get("battery_voltage"),  # type: ignore[arg-type]
                        battery_level=battery.get("battery_level"),  # type: ignore[arg-type]
                        vcc_raw=telemetry.get("vcc_raw"),  # type: ignore[arg-type]
                        vcc_v=telemetry.get("vcc"),  # type: ignore[arg-type]
                        rail_33_raw=telemetry.get("3.3v"),  # type: ignore[arg-type]
                        device_datetime=telemetry.get("datetime"),  # type: ignore[arg-type]
                    )
                )

            firmware = parsed.get("firmware")
            if isinstance(firmware, dict):
                raw_reason = firmware.get("reset_reason_raw")
                session.add(
                    FirmwareState(
                        snapshot_id=snapshot_id,
                        captured_at=captured_at,
                        hardware_version=firmware.get("hardware_version"),  # type: ignore[arg-type]
                        bootloader_version=firmware.get("bootloader_version"),  # type: ignore[arg-type]
                        reset_reason=firmware.get("reset_reason"),  # type: ignore[arg-type]
                        reset_reason_raw=int.from_bytes(raw_reason, "little")
                        if isinstance(raw_reason, (bytes, bytearray))
                        else None,
                    )
                )

            module_info = parsed.get("module_info")
            if isinstance(module_info, dict):
                serial = module_info.get("serial")
                session.add(
                    ModuleInfoState(
                        snapshot_id=snapshot_id,
                        captured_at=captured_at,
                        app_version=module_info.get("app_version"),  # type: ignore[arg-type]
                        serial=serial.hex() if isinstance(serial, bytes) else serial,
                    )
                )

            lifetime = parsed.get("lifetime")
            if isinstance(lifetime, dict):
                session.add(
                    LifetimeStatsState(
                        snapshot_id=snapshot_id,
                        captured_at=captured_at,
                        count_restart=lifetime.get("count-restart"),  # type: ignore[arg-type]
                        count_lifetime=lifetime.get("count-lifetime"),  # type: ignore[arg-type]
                    )
                )

            today = parsed.get("today")
            if isinstance(today, dict):
                session.add(
                    TodayStatsState(
                        snapshot_id=snapshot_id,
                        captured_at=captured_at,
                        count_normal=today.get("count-normal"),  # type: ignore[arg-type]
                        runtime_normal=today.get("runtime-normal"),  # type: ignore[arg-type]
                        count_stagnation=today.get("count-stagnation"),  # type: ignore[arg-type]
                        runtime_stagnation=today.get("runtime-stagnation"),  # type: ignore[arg-type]
                        aerator_lpm=today.get("aerator-liters-per-minute"),  # type: ignore[arg-type]
                        consumption_normal_l=today.get("consumption-normal-liters"),  # type: ignore[arg-type]
                        consumption_stagnation_l=today.get("consumption-stagnation-liters"),  # type: ignore[arg-type]
                    )
                )

            config = parsed.get("config")
            if isinstance(config, dict):
                _upsert_config(
                    session,
                    device_id,
                    snapshot_id,
                    captured_at,
                    config,
                    redact_secrets=redact_secrets,
                )

            calendar = parsed.get("calendar")
            if isinstance(calendar, list):
                _upsert_calendar(
                    session, device_id, snapshot_id, captured_at, calendar
                )

            daily_stats = parsed.get("daily_stats")
            if isinstance(daily_stats, list):
                _upsert_daily_stats(
                    session, device_id, snapshot_id, captured_at, daily_stats
                )

            events = parsed.get("events")
            if isinstance(events, list):
                _upsert_events(session, device_id, snapshot_id, captured_at, events)

            session.commit()
            return snapshot_id

    # -- recovery / diagnostics ---------------------------------------------

    def recover_after_restart(self, run_id: int) -> None:
        """Close stale online periods and open off periods after a restart."""
        now = utcnow()
        for device in self.list_devices():
            open_online = self.get_open_online_period(device.id)  # type: ignore[arg-type]
            if open_online is not None and open_online.id is not None:
                self.close_online_period(
                    open_online.id,
                    ended_at=open_online.last_seen_at,
                    detected_at=now,
                    reason="recorder_restart",
                )

            if self.mark_open_off_period_unobserved(device.id):  # type: ignore[arg-type]
                continue

            with Session(self.engine) as session:
                last_online = session.exec(
                    select(OnlinePeriod)
                    .where(OnlinePeriod.device_id == device.id)
                    .order_by(OnlinePeriod.started_at.desc())
                ).first()
                start = (
                    (last_online.ended_at or last_online.last_seen_at)
                    if last_online is not None
                    else (device.last_seen_at or now)
                )
                if start > now:
                    start = now
                session.add(
                    OffPeriod(
                        device_id=device.id,
                        previous_online_period_id=last_online.id if last_online else None,
                        started_at=start,
                        start_accuracy="recorder_restart",
                        fully_observed=False,
                    )
                )
                session.commit()

    def save_scan_run(
        self,
        *,
        recorder_run_id: int | None,
        started_at: dt.datetime,
        finished_at: dt.datetime,
        duration_ms: int,
        device_count: int,
        ssc_count: int,
        found_addresses: list[str],
        error: str | None = None,
    ) -> None:
        with Session(self.engine) as session:
            session.add(
                ScanRun(
                    recorder_run_id=recorder_run_id,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                    device_count=device_count,
                    ssc_count=ssc_count,
                    found_addresses=found_addresses,
                    error=error,
                )
            )
            session.commit()


def _config_parts(value: object) -> tuple[str, str | None, float | None, bool | None]:
    """Split a parsed config value into typed, queryable columns."""
    if isinstance(value, bool):
        return "bool", str(value), None, value
    if isinstance(value, int):
        return "int", str(value), float(value), None
    if isinstance(value, float):
        return "float", repr(value), value, None
    if isinstance(value, dt.datetime):
        return "datetime", value.isoformat(), value.timestamp(), None
    if isinstance(value, dt.date):
        return "date", value.isoformat(), float(value.toordinal()), None
    if isinstance(value, str):
        return "str", value, None, None
    return "json", _json_text(value), None, None


def _ensure_eeprom_image(
    session: Session,
    image: bytes,
    *,
    captured_at: dt.datetime,
    start_address: int,
    coverage: int,
) -> EepromImage:
    sha256 = hashlib.sha256(image).hexdigest()
    existing = session.exec(
        select(EepromImage).where(EepromImage.sha256 == sha256)
    ).first()
    if existing is not None:
        existing.last_seen_at = captured_at
        existing.seen_count += 1
        session.add(existing)
        return existing

    compressed = zlib.compress(image, 6)
    stored = EepromImage(
        sha256=sha256,
        start_address=start_address,
        length=len(image),
        coverage=coverage,
        codec="zlib",
        data=compressed,
        first_seen_at=captured_at,
        last_seen_at=captured_at,
        seen_count=1,
    )
    session.add(stored)
    session.flush()
    return stored


def _upsert_config(
    session: Session,
    device_id: int,
    snapshot_id: int,
    captured_at: dt.datetime,
    config: dict[str, object],
    *,
    redact_secrets: bool,
) -> None:
    for field in FIELDS:
        if field.name not in config:
            continue
        value = config[field.name]
        if redact_secrets and field.name in SECRET_FIELD_NAMES:
            value_type, value_text, value_number, value_bool = (
                "redacted",
                "***",
                None,
                None,
            )
        else:
            value_type, value_text, value_number, value_bool = _config_parts(value)
        value_sha256 = _sha256_text(
            {"type": value_type, "text": value_text, "number": value_number, "bool": value_bool}
        )

        existing = session.get(ConfigFieldValue, (device_id, field.name))
        if existing is None:
            session.add(
                ConfigFieldValue(
                    device_id=device_id,
                    name=field.name,
                    address=field.address,
                    length=field.length,
                    value_type=value_type,
                    value_text=value_text,
                    value_number=value_number,
                    value_bool=value_bool,
                    value_sha256=value_sha256,
                    first_seen_at=captured_at,
                    last_seen_at=captured_at,
                    last_snapshot_id=snapshot_id,
                )
            )
            continue

        if existing.value_sha256 != value_sha256:
            session.add(
                ConfigChange(
                    device_id=device_id,
                    name=field.name,
                    changed_at=captured_at,
                    old_value_text=existing.value_text,
                    new_value_text=value_text,
                    old_value_number=existing.value_number,
                    new_value_number=value_number,
                    snapshot_id=snapshot_id,
                )
            )

        existing.address = field.address
        existing.length = field.length
        existing.value_type = value_type
        existing.value_text = value_text
        existing.value_number = value_number
        existing.value_bool = value_bool
        existing.value_sha256 = value_sha256
        existing.last_seen_at = captured_at
        existing.last_snapshot_id = snapshot_id
        session.add(existing)


def _upsert_calendar(
    session: Session,
    device_id: int,
    snapshot_id: int,
    captured_at: dt.datetime,
    calendar: list[dict[str, object]],
) -> None:
    for index, slot in enumerate(calendar):
        mapped = slot.get("bitmask_mapped") or ("", None)
        if isinstance(mapped, (tuple, list)) and len(mapped) == 2:
            mode, days = mapped
        else:
            mode, days = str(mapped), None
        existing = session.get(CalendarSlot, (device_id, index))
        if existing is None:
            session.add(
                CalendarSlot(
                    device_id=device_id,
                    slot_index=index,
                    bitmask=int(slot.get("bitmask", 0)),
                    mode=str(mode),
                    days=days,
                    hour=int(slot.get("hour", 0)),
                    minute=int(slot.get("minute", 0)),
                    second=int(slot.get("second", 0)),
                    runtime_s=int(slot.get("runtime", 0)),
                    first_seen_at=captured_at,
                    last_seen_at=captured_at,
                    last_snapshot_id=snapshot_id,
                )
            )
        else:
            existing.bitmask = int(slot.get("bitmask", 0))
            existing.mode = str(mode)
            existing.days = days
            existing.hour = int(slot.get("hour", 0))
            existing.minute = int(slot.get("minute", 0))
            existing.second = int(slot.get("second", 0))
            existing.runtime_s = int(slot.get("runtime", 0))
            existing.last_seen_at = captured_at
            existing.last_snapshot_id = snapshot_id
            session.add(existing)


def _upsert_daily_stats(
    session: Session,
    device_id: int,
    snapshot_id: int,
    captured_at: dt.datetime,
    daily_stats: list[tuple[object, dict[str, object]]],
) -> None:
    for day, stats in daily_stats:
        if isinstance(day, dt.datetime):
            stat_date = day.date()
        elif isinstance(day, dt.date):
            stat_date = day
        else:
            continue
        value_sha256 = _sha256_text(stats)
        existing = session.get(DailyStat, (device_id, stat_date))
        values = {
            "count_normal": stats.get("count-normal"),
            "runtime_normal": stats.get("runtime-normal"),
            "count_stagnation": stats.get("count-stagnation"),
            "runtime_stagnation": stats.get("runtime-stagnation"),
            "aerator_lpm": stats.get("aerator-liters-per-minute"),
            "consumption_normal_l": stats.get("consumption-normal-liters"),
            "consumption_stagnation_l": stats.get("consumption-stagnation-liters"),
        }
        if existing is None:
            session.add(
                DailyStat(
                    device_id=device_id,
                    stat_date=stat_date,
                    first_seen_at=captured_at,
                    last_seen_at=captured_at,
                    last_snapshot_id=snapshot_id,
                    value_sha256=value_sha256,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.last_seen_at = captured_at
            existing.last_snapshot_id = snapshot_id
            existing.value_sha256 = value_sha256
            session.add(existing)


def _upsert_events(
    session: Session,
    device_id: int,
    snapshot_id: int,
    captured_at: dt.datetime,
    events: list[dict[str, object]],
) -> None:
    for event in events:
        entry_sha256 = str(event.get("entry_sha256", ""))
        log_type = str(event.get("log_type", "unknown"))
        if not entry_sha256:
            continue
        existing = session.exec(
            select(EventLogEntry)
            .where(EventLogEntry.device_id == device_id)
            .where(EventLogEntry.log_type == log_type)
            .where(EventLogEntry.entry_sha256 == entry_sha256)
        ).first()
        if existing is not None:
            existing.last_seen_at = captured_at
            existing.last_snapshot_id = snapshot_id
            session.add(existing)
            continue
        session.add(
            EventLogEntry(
                device_id=device_id,
                log_type=log_type,
                slot_index=int(event.get("slot_index", 0)),
                occurred_at=event.get("occurred_at"),  # type: ignore[arg-type]
                status=event.get("status"),  # type: ignore[arg-type]
                duration_s=event.get("duration_s"),  # type: ignore[arg-type]
                entry_sha256=entry_sha256,
                raw=event.get("raw", b""),  # type: ignore[arg-type]
                first_seen_at=captured_at,
                last_seen_at=captured_at,
                last_snapshot_id=snapshot_id,
            )
        )