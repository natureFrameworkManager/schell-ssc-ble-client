"""SQLModel table definitions for the recorder history.

Design notes
------------
* Timestamps are host UTC timestamps.  Device RTC timestamps are kept in the
  separate ``device_datetime`` columns.
* Closed intervals store ``duration_s`` explicitly.  Open intervals
  (``ended_at IS NULL``) are cheap: their duration is computed on demand and
  the row is not rewritten on every scan.
* Raw EEPROM images are content-addressed by SHA-256, so repeated identical
  dumps share one BLOB.
* Presence samples exist only for scans in which a device was found.  While a
  device is off, no per-scan rows are written; the off interval is represented
  by a single :class:`OffPeriod` row.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Column, DateTime, Index, LargeBinary, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> dt.datetime:
    """Return the current UTC timestamp (timezone aware)."""
    return dt.datetime.now(dt.UTC)


class Device(SQLModel, table=True):
    """A discovered SSC device.

    Devices are not configured up-front: a row is created the first time the
    recorder sees the peripheral.  ``address`` is the primary lookup key; if a
    device advertises a stable serial number it is stored as well.
    """

    __tablename__ = "device"

    id: int | None = Field(default=None, primary_key=True)
    address: str = Field(index=True, unique=True, max_length=32)
    identifier: str = Field(default="", max_length=64)
    serial: str | None = Field(default=None, index=True, max_length=64)
    display_name: str | None = Field(default=None, max_length=64)
    product: str | None = Field(default=None, max_length=128)
    first_seen_at: dt.datetime = Field(default_factory=utcnow)
    last_seen_at: dt.datetime | None = Field(default=None, index=True)


class RecorderRun(SQLModel, table=True):
    """One process lifetime.

    The rows make observation gaps explicit: an off interval that spans a run
    boundary was not fully observed by the recorder.
    """

    __tablename__ = "recorder_run"

    id: int | None = Field(default=None, primary_key=True)
    started_at: dt.datetime = Field(default_factory=utcnow, index=True)
    stopped_at: dt.datetime | None = Field(default=None, index=True)
    host: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=32)
    stop_reason: str | None = Field(default=None, max_length=64)


class OnlinePeriod(SQLModel, table=True):
    """One continuous period during which a device was seen by scans."""

    __tablename__ = "online_period"

    id: int | None = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id", index=True)
    recorder_run_id: int | None = Field(default=None, foreign_key="recorder_run.id")

    started_at: dt.datetime = Field(index=True)
    last_seen_at: dt.datetime
    ended_at: dt.datetime | None = Field(default=None, index=True)
    offline_detected_at: dt.datetime | None = None
    ended_reason: str | None = Field(default=None, max_length=64)
    duration_s: int | None = None
    scan_count: int = 0

    query_attempts: int = 0
    queried_at: dt.datetime | None = None
    query_status: str = Field(default="pending", max_length=16)

    __table_args__ = (
        Index("ix_online_device_started", "device_id", "started_at"),
        Index("ix_online_open", "device_id", "ended_at"),
    )


class OffPeriod(SQLModel, table=True):
    """One continuous period during which a device was not seen.

    ``started_at`` is normally the last successful scan (``last_seen_at``), not
    the time the recorder noticed the absence.  ``start_accuracy`` documents
    how the start was derived; the scan interval is the uncertainty.
    """

    __tablename__ = "off_period"

    id: int | None = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id", index=True)
    previous_online_period_id: int | None = Field(
        default=None, foreign_key="online_period.id"
    )
    next_online_period_id: int | None = Field(
        default=None, foreign_key="online_period.id"
    )

    started_at: dt.datetime = Field(index=True)
    ended_at: dt.datetime | None = Field(default=None, index=True)
    duration_s: int | None = None

    # observed | last_seen_estimate | recorder_restart | bootstrap
    start_accuracy: str = Field(default="observed", max_length=24)
    fully_observed: bool = True

    __table_args__ = (
        Index("ix_off_device_started", "device_id", "started_at"),
    )


class PresenceSample(SQLModel, table=True):
    """A scan in which a device was found.

    One row per found scan; there are deliberately no rows for scans in which
    the device was absent.  The composite primary key keeps the table compact.
    """

    __tablename__ = "presence_sample"

    online_period_id: int = Field(foreign_key="online_period.id", primary_key=True)
    observed_at: dt.datetime = Field(primary_key=True)
    device_id: int = Field(foreign_key="device.id", index=True)

    rssi: int | None = None
    battery_voltage_adv: int | None = None
    battery_level: int | None = None
    advertisement_json: str | None = None

    __table_args__ = (
        Index("ix_presence_device_time", "device_id", "observed_at"),
        {"sqlite_with_rowid": False},
    )


class EepromImage(SQLModel, table=True):
    """A deduplicated full raw EEPROM image."""

    __tablename__ = "eeprom_image"

    id: int | None = Field(default=None, primary_key=True)
    sha256: str = Field(index=True, unique=True, max_length=64)
    start_address: int = 0
    length: int = 0x4000
    coverage: int = 0
    codec: str = Field(default="zlib", max_length=16)
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    first_seen_at: dt.datetime = Field(default_factory=utcnow)
    last_seen_at: dt.datetime = Field(default_factory=utcnow)
    seen_count: int = 1


class StateSnapshot(SQLModel, table=True):
    """One timestamped query of a device's complete state."""

    __tablename__ = "state_snapshot"

    id: int | None = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id", index=True)
    online_period_id: int | None = Field(
        default=None, foreign_key="online_period.id", index=True
    )
    eeprom_image_id: int | None = Field(
        default=None, foreign_key="eeprom_image.id", index=True
    )

    captured_at: dt.datetime = Field(default_factory=utcnow, index=True)
    completed_at: dt.datetime | None = None
    device_datetime: dt.datetime | None = Field(default=None, sa_type=DateTime)

    query_status: str = Field(default="ok", max_length=16)
    coverage: int = 0
    missing_ranges: list[list[int]] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    error: str | None = None

    __table_args__ = (
        Index("ix_snapshot_device_captured", "device_id", "captured_at"),
    )


class TelemetryState(SQLModel, table=True):
    __tablename__ = "telemetry_state"

    snapshot_id: int = Field(foreign_key="state_snapshot.id", primary_key=True)
    captured_at: dt.datetime = Field(index=True)

    temperature_raw: int | None = None
    battery_voltage_raw: int | None = None
    battery_voltage_v: float | None = None
    battery_level: int | None = None
    vcc_raw: int | None = None
    vcc_v: float | None = None
    rail_33_raw: int | None = None
    device_datetime: dt.datetime | None = Field(default=None, sa_type=DateTime)


class FirmwareState(SQLModel, table=True):
    __tablename__ = "firmware_state"

    snapshot_id: int = Field(foreign_key="state_snapshot.id", primary_key=True)
    captured_at: dt.datetime = Field(index=True)

    hardware_version: str | None = Field(default=None, max_length=32)
    bootloader_version: str | None = Field(default=None, max_length=32)
    reset_reason: str | None = Field(default=None, max_length=128)
    reset_reason_raw: int | None = None


class ModuleInfoState(SQLModel, table=True):
    __tablename__ = "module_info_state"

    snapshot_id: int = Field(foreign_key="state_snapshot.id", primary_key=True)
    captured_at: dt.datetime = Field(index=True)

    app_version: str | None = Field(default=None, max_length=32)
    serial: str | None = Field(default=None, max_length=64)


class LifetimeStatsState(SQLModel, table=True):
    __tablename__ = "lifetime_stats_state"

    snapshot_id: int = Field(foreign_key="state_snapshot.id", primary_key=True)
    captured_at: dt.datetime = Field(index=True)

    count_restart: int | None = None
    count_lifetime: int | None = None


class TodayStatsState(SQLModel, table=True):
    __tablename__ = "today_stats_state"

    snapshot_id: int = Field(foreign_key="state_snapshot.id", primary_key=True)
    captured_at: dt.datetime = Field(index=True)

    count_normal: int | None = None
    runtime_normal: int | None = None
    count_stagnation: int | None = None
    runtime_stagnation: int | None = None
    aerator_lpm: int | None = None
    consumption_normal_l: float | None = None
    consumption_stagnation_l: float | None = None


class ConfigFieldValue(SQLModel, table=True):
    """Latest parsed value of one scalar EEPROM field.

    The raw per-snapshot state is preserved by :class:`StateSnapshot` and
    :class:`EepromImage`; this table avoids duplicating ~50 unchanged fields on
    every query.  :class:`ConfigChange` records parsed value changes.
    """

    __tablename__ = "config_field_value"

    device_id: int = Field(foreign_key="device.id", primary_key=True)
    name: str = Field(primary_key=True, index=True, max_length=64)

    address: int
    length: int
    value_type: str = Field(max_length=16)
    value_text: str | None = None
    value_number: float | None = Field(default=None, index=True)
    value_bool: bool | None = None
    value_sha256: str = Field(max_length=64)

    first_seen_at: dt.datetime
    last_seen_at: dt.datetime
    last_snapshot_id: int = Field(foreign_key="state_snapshot.id")


class ConfigChange(SQLModel, table=True):
    """A parsed config value changed between two snapshots."""

    __tablename__ = "config_change"

    id: int | None = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id", index=True)
    name: str = Field(index=True, max_length=64)
    changed_at: dt.datetime = Field(index=True)
    old_value_text: str | None = None
    new_value_text: str | None = None
    old_value_number: float | None = None
    new_value_number: float | None = None
    snapshot_id: int = Field(foreign_key="state_snapshot.id", index=True)


class CalendarSlot(SQLModel, table=True):
    """Latest parsed weekly-calendar slots for a device."""

    __tablename__ = "calendar_slot"

    device_id: int = Field(foreign_key="device.id", primary_key=True)
    slot_index: int = Field(primary_key=True)

    bitmask: int
    mode: str = Field(max_length=32)
    days: str | None = Field(default=None, max_length=64)
    hour: int
    minute: int
    second: int
    runtime_s: int

    first_seen_at: dt.datetime
    last_seen_at: dt.datetime
    last_snapshot_id: int = Field(foreign_key="state_snapshot.id")


class DailyStat(SQLModel, table=True):
    """Per-day consumption statistics.

    Keyed by semantic day, not by snapshot, so repeated queries do not create
    hundreds of duplicate daily rows.
    """

    __tablename__ = "daily_stat"

    device_id: int = Field(foreign_key="device.id", primary_key=True)
    stat_date: dt.date = Field(primary_key=True, index=True)

    count_normal: int | None = None
    runtime_normal: int | None = None
    count_stagnation: int | None = None
    runtime_stagnation: int | None = None
    aerator_lpm: int | None = None
    consumption_normal_l: float | None = None
    consumption_stagnation_l: float | None = None

    first_seen_at: dt.datetime
    last_seen_at: dt.datetime
    last_snapshot_id: int = Field(foreign_key="state_snapshot.id")
    value_sha256: str = Field(max_length=64)

    __table_args__ = (
        Index("ix_daily_device_date", "device_id", "stat_date"),
    )


class EventLogEntry(SQLModel, table=True):
    """One entry of one of the four EEPROM event logs."""

    __tablename__ = "event_log_entry"

    id: int | None = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id", index=True)
    log_type: str = Field(index=True, max_length=64)
    slot_index: int

    occurred_at: dt.datetime | None = Field(
        default=None, index=True, sa_type=DateTime
    )
    status: str | None = Field(default=None, max_length=32)
    duration_s: int | None = None
    entry_sha256: str = Field(max_length=64)
    raw: bytes = Field(sa_column=Column(LargeBinary, nullable=False))

    first_seen_at: dt.datetime
    last_seen_at: dt.datetime
    last_snapshot_id: int = Field(foreign_key="state_snapshot.id")

    __table_args__ = (
        UniqueConstraint(
            "device_id",
            "log_type",
            "entry_sha256",
            name="uq_event_identity",
        ),
    )


class ScanRun(SQLModel, table=True):
    """Optional diagnostics for every scan, including empty ones."""

    __tablename__ = "scan_run"

    id: int | None = Field(default=None, primary_key=True)
    recorder_run_id: int | None = Field(default=None, foreign_key="recorder_run.id")
    started_at: dt.datetime = Field(index=True)
    finished_at: dt.datetime | None = None
    duration_ms: int | None = None
    device_count: int = 0
    ssc_count: int = 0
    found_addresses: list[str] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    error: str | None = None