"""Pydantic response models for the web API."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field


class RecorderRunDTO(BaseModel):
    id: int
    started_at: dt.datetime
    stopped_at: dt.datetime | None = None
    host: str | None = None
    version: str | None = None
    stop_reason: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    database: str
    database_exists: bool
    schema_version: int | None = None
    expected_schema_version: int | None = None
    tables_ok: bool = False
    device_count: int = 0
    recorder_running: bool = False
    latest_run: RecorderRunDTO | None = None
    latest_scan_at: dt.datetime | None = None
    detail: str | None = None


class DeviceSummary(BaseModel):
    id: int
    address: str
    identifier: str
    serial: str | None = None
    display_name: str | None = None
    product: str | None = None

    state: Literal["online", "off", "unknown"] = "unknown"
    recorder_running: bool = False
    online_since: dt.datetime | None = None
    offline_since: dt.datetime | None = None
    current_interval_s: int | None = None
    last_seen_at: dt.datetime | None = None
    observation_gap: bool = False

    latest_snapshot_at: dt.datetime | None = None
    latest_query_status: str | None = None
    latest_battery_level: int | None = None
    latest_battery_voltage_v: float | None = None
    state_age_s: int | None = None


class PresenceInterval(BaseModel):
    kind: Literal["online", "off"]
    started_at: dt.datetime
    ended_at: dt.datetime | None = None
    duration_s: int
    open: bool = False
    clipped_start: bool = False
    clipped_end: bool = False
    fully_observed: bool = True
    start_accuracy: str | None = None
    query_status: str | None = None
    scan_count: int | None = None


class PresenceSummary(BaseModel):
    online_s: int = 0
    off_s: int = 0
    uptime_pct: float = 0.0
    sessions: int = 0
    longest_online_s: int = 0
    longest_off_s: int = 0
    found_samples: int = 0
    observation_gap: bool = False


class PresenceResponse(BaseModel):
    device_id: int
    from_at: dt.datetime = Field(alias="from")
    to_at: dt.datetime = Field(alias="to")
    now: dt.datetime
    recorder_running: bool
    intervals: list[PresenceInterval]
    summary: PresenceSummary

    model_config = {"populate_by_name": True}


class PresenceSampleDTO(BaseModel):
    observed_at: dt.datetime
    rssi: int | None = None
    battery_voltage_adv: int | None = None
    battery_level: int | None = None


class PresenceSamplesResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PresenceSampleDTO]


class AvailabilityPoint(BaseModel):
    bucket_start: dt.datetime
    online_s: int
    off_s: int
    unknown_s: int


class AvailabilityResponse(BaseModel):
    device_id: int
    from_at: dt.datetime = Field(alias="from")
    to_at: dt.datetime = Field(alias="to")
    bucket: str
    points: list[AvailabilityPoint]

    model_config = {"populate_by_name": True}


class EepromMeta(BaseModel):
    sha256: str
    start_address: int
    length: int
    coverage: int
    codec: str
    first_seen_at: dt.datetime | None = None
    last_seen_at: dt.datetime | None = None
    seen_count: int | None = None


class SnapshotSummary(BaseModel):
    id: int
    online_period_id: int | None = None
    captured_at: dt.datetime
    completed_at: dt.datetime | None = None
    device_datetime: dt.datetime | None = None
    query_status: str
    coverage: int
    missing_ranges: list[list[int]] | None = None
    error: str | None = None
    eeprom: EepromMeta | None = None


class SnapshotListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[SnapshotSummary]


class TelemetryDTO(BaseModel):
    snapshot_id: int
    captured_at: dt.datetime
    temperature_raw: int | None = None
    battery_voltage_raw: int | None = None
    battery_voltage_v: float | None = None
    battery_level: int | None = None
    vcc_raw: int | None = None
    vcc_v: float | None = None
    rail_33_raw: int | None = None
    device_datetime: dt.datetime | None = None


class FirmwareDTO(BaseModel):
    snapshot_id: int
    captured_at: dt.datetime
    hardware_version: str | None = None
    bootloader_version: str | None = None
    reset_reason: str | None = None
    reset_reason_raw: int | None = None


class ModuleInfoDTO(BaseModel):
    snapshot_id: int
    captured_at: dt.datetime
    app_version: str | None = None
    serial: str | None = None


class LifetimeStatsDTO(BaseModel):
    snapshot_id: int
    captured_at: dt.datetime
    count_restart: int | None = None
    count_lifetime: int | None = None


class TodayStatsDTO(BaseModel):
    snapshot_id: int
    captured_at: dt.datetime
    count_normal: int | None = None
    runtime_normal: int | None = None
    count_stagnation: int | None = None
    runtime_stagnation: int | None = None
    aerator_lpm: int | None = None
    consumption_normal_l: float | None = None
    consumption_stagnation_l: float | None = None


class ConfigFieldDTO(BaseModel):
    name: str
    address: int
    length: int
    value_type: str
    value_text: str | None = None
    value_number: float | None = None
    value_bool: bool | None = None
    first_seen_at: dt.datetime | None = None
    last_seen_at: dt.datetime | None = None
    last_snapshot_id: int | None = None


class CalendarSlotDTO(BaseModel):
    slot_index: int
    bitmask: int
    mode: str
    days: str | None = None
    hour: int
    minute: int
    second: int
    runtime_s: int
    reserved_hex: str | None = None


class DailyStatDTO(BaseModel):
    date: dt.date
    count_normal: int | None = None
    runtime_normal: int | None = None
    count_stagnation: int | None = None
    runtime_stagnation: int | None = None
    aerator_lpm: int | None = None
    consumption_normal_l: float | None = None
    consumption_stagnation_l: float | None = None
    first_seen_at: dt.datetime | None = None
    last_seen_at: dt.datetime | None = None
    last_snapshot_id: int | None = None


class EventLogDTO(BaseModel):
    id: int | None = None
    log_type: str
    slot_index: int
    occurred_at: dt.datetime | None = None
    status: str | None = None
    duration_s: int | None = None
    entry_sha256: str | None = None
    raw_hex: str | None = None
    first_seen_at: dt.datetime | None = None
    last_seen_at: dt.datetime | None = None
    last_snapshot_id: int | None = None


class SnapshotStateResponse(BaseModel):
    device: DeviceSummary
    snapshot: SnapshotSummary | None = None
    state_source: str | None = None
    telemetry: TelemetryDTO | None = None
    firmware: FirmwareDTO | None = None
    module_info: ModuleInfoDTO | None = None
    lifetime: LifetimeStatsDTO | None = None
    today: TodayStatsDTO | None = None
    config: list[ConfigFieldDTO] = Field(default_factory=list)
    calendar: list[CalendarSlotDTO] = Field(default_factory=list)
    daily_stats: list[DailyStatDTO] = Field(default_factory=list)
    events: list[EventLogDTO] = Field(default_factory=list)


class TelemetryPoint(BaseModel):
    captured_at: dt.datetime
    device_datetime: dt.datetime | None = None
    battery_voltage_v: float | None = None
    battery_level: int | None = None
    vcc_v: float | None = None
    temperature_raw: int | None = None
    rail_33_raw: int | None = None
    samples: int = 1


class TelemetryHistoryResponse(BaseModel):
    device_id: int
    from_at: dt.datetime = Field(alias="from")
    to_at: dt.datetime = Field(alias="to")
    bucket: str
    points: list[TelemetryPoint]

    model_config = {"populate_by_name": True}


class CounterPoint(BaseModel):
    captured_at: dt.datetime
    device_datetime: dt.datetime | None = None
    count_normal: int | None = None
    runtime_normal: int | None = None
    count_stagnation: int | None = None
    runtime_stagnation: int | None = None
    consumption_normal_l: float | None = None
    consumption_stagnation_l: float | None = None
    count_restart: int | None = None
    count_lifetime: int | None = None


class CounterHistoryResponse(BaseModel):
    device_id: int
    from_at: dt.datetime = Field(alias="from")
    to_at: dt.datetime = Field(alias="to")
    points: list[CounterPoint]

    model_config = {"populate_by_name": True}


class DailyStatsResponse(BaseModel):
    device_id: int
    from_date: dt.date | None = None
    to_date: dt.date | None = None
    items: list[DailyStatDTO]


class EventHistoryResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[EventLogDTO]


class ConfigChangeDTO(BaseModel):
    id: int
    name: str
    changed_at: dt.datetime
    old_value_text: str | None = None
    new_value_text: str | None = None
    old_value_number: float | None = None
    new_value_number: float | None = None
    snapshot_id: int


class ConfigChangesResponse(BaseModel):
    device_id: int
    items: list[ConfigChangeDTO]


class ConfigFieldChange(BaseModel):
    name: str
    base_value: Any = None
    target_value: Any = None


class CompareResponse(BaseModel):
    device_id: int
    base_snapshot_id: int
    target_snapshot_id: int
    config_changes: list[ConfigFieldChange]
    telemetry_changes: dict[str, Any]
    counter_changes: dict[str, Any]
    daily_changes: list[dict[str, Any]]
    new_events: list[EventLogDTO]
    removed_events: list[EventLogDTO]


class RecorderRunsResponse(BaseModel):
    items: list[RecorderRunDTO]