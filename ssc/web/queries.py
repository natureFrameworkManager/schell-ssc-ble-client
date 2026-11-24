"""Read-only queries powering the web API."""

from __future__ import annotations

import datetime as dt
import json
import logging
import zlib
from collections import defaultdict
from typing import Any

from sqlalchemy import func, or_
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
    StateSnapshot,
    TelemetryState,
    TodayStatsState,
    utcnow,
)
from ssc.eeprom.image import parse_eeprom_image
from ssc.eeprom.layout import FIELDS
from ssc.web.schemas import (
    AvailabilityPoint,
    AvailabilityResponse,
    CalendarSlotDTO,
    CompareResponse,
    ConfigChangeDTO,
    ConfigFieldChange,
    ConfigFieldDTO,
    CounterHistoryResponse,
    CounterPoint,
    DailyStatDTO,
    DailyStatsResponse,
    DeviceSummary,
    EepromMeta,
    EventHistoryResponse,
    EventLogDTO,
    FirmwareDTO,
    LifetimeStatsDTO,
    ModuleInfoDTO,
    PresenceInterval,
    PresenceResponse,
    PresenceSampleDTO,
    PresenceSamplesResponse,
    PresenceSummary,
    SnapshotListResponse,
    SnapshotStateResponse,
    SnapshotSummary,
    TelemetryDTO,
    TelemetryHistoryResponse,
    TelemetryPoint,
    TodayStatsDTO,
)

logger = logging.getLogger(__name__)

SECRET_FIELD_NAMES = frozenset({"EEPROM_DevicePassword", "EEPROM_Password"})
FIELD_BY_NAME = {field.name: field for field in FIELDS}
DAY = dt.timedelta(days=1)
HOUR = dt.timedelta(hours=1)


def utc(value: dt.datetime | None, default: dt.datetime | None = None) -> dt.datetime:
    if value is None:
        value = default or utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def date_range(
    from_ts: dt.datetime | None,
    to_ts: dt.datetime | None,
    *,
    default_days: int,
) -> tuple[dt.datetime, dt.datetime]:
    to_value = utc(to_ts, utcnow())
    from_value = utc(from_ts, to_value - dt.timedelta(days=default_days))
    return from_value, to_value


def _latest_run(session: Session) -> RecorderRun | None:
    return session.exec(
        select(RecorderRun).order_by(RecorderRun.started_at.desc()).limit(1)
    ).first()


def _latest_snapshots(session: Session) -> dict[int, StateSnapshot]:
    latest_ids = select(func.max(StateSnapshot.id)).group_by(StateSnapshot.device_id)
    rows = session.exec(
        select(StateSnapshot).where(StateSnapshot.id.in_(latest_ids))
    ).all()
    return {row.device_id: row for row in rows}


def _open_periods(
    session: Session,
) -> tuple[dict[int, OnlinePeriod], dict[int, OffPeriod]]:
    online: dict[int, OnlinePeriod] = {}
    offline: dict[int, OffPeriod] = {}
    for period in session.exec(
        select(OnlinePeriod).where(OnlinePeriod.ended_at.is_(None))
    ).all():
        current = online.get(period.device_id)
        if current is None or period.started_at > current.started_at:
            online[period.device_id] = period
    for period in session.exec(
        select(OffPeriod).where(OffPeriod.ended_at.is_(None))
    ).all():
        current = offline.get(period.device_id)
        if current is None or period.started_at > current.started_at:
            offline[period.device_id] = period
    return online, offline


def _telemetry_for_snapshots(
    session: Session, snapshot_ids: list[int]
) -> dict[int, TelemetryState]:
    if not snapshot_ids:
        return {}
    rows = session.exec(
        select(TelemetryState).where(TelemetryState.snapshot_id.in_(snapshot_ids))
    ).all()
    return {row.snapshot_id: row for row in rows}


def _eeprom_meta(session: Session, image_id: int | None) -> EepromMeta | None:
    if image_id is None:
        return None
    row = session.get(EepromImage, image_id)
    if row is None:
        return None
    return EepromMeta(
        sha256=row.sha256,
        start_address=row.start_address,
        length=row.length,
        coverage=row.coverage,
        codec=row.codec,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        seen_count=row.seen_count,
    )


def _snapshot_summary(
    snapshot: StateSnapshot, eeprom: EepromMeta | None
) -> SnapshotSummary:
    return SnapshotSummary(
        id=snapshot.id,  # type: ignore[arg-type]
        online_period_id=snapshot.online_period_id,
        captured_at=snapshot.captured_at,
        completed_at=snapshot.completed_at,
        device_datetime=snapshot.device_datetime,
        query_status=snapshot.query_status,
        coverage=snapshot.coverage,
        missing_ranges=snapshot.missing_ranges,
        error=snapshot.error,
        eeprom=eeprom,
    )


def list_device_summaries(session: Session) -> list[DeviceSummary]:
    devices = session.exec(select(Device).order_by(Device.id)).all()
    if not devices:
        return []
    run = _latest_run(session)
    running = bool(run and run.stopped_at is None)
    open_online, open_off = _open_periods(session)
    latest = _latest_snapshots(session)
    telemetry = _telemetry_for_snapshots(
        session,
        [snapshot.id for snapshot in latest.values() if snapshot.id is not None],
    )
    now = utcnow()
    result: list[DeviceSummary] = []

    for device in devices:
        online = open_online.get(device.id)  # type: ignore[arg-type]
        offline = open_off.get(device.id)  # type: ignore[arg-type]
        snapshot = latest.get(device.id)  # type: ignore[arg-type]
        telemetry_row = telemetry.get(snapshot.id) if snapshot and snapshot.id else None

        state = "unknown"
        online_since = None
        offline_since = None
        current_interval_s = None
        observation_gap = False

        if running and online is not None:
            state = "online"
            online_since = online.started_at
            current_interval_s = max(
                0, int((now - utc(online.started_at)).total_seconds())
            )
        elif running and offline is not None:
            state = "off"
            offline_since = offline.started_at
            current_interval_s = max(
                0, int((now - utc(offline.started_at)).total_seconds())
            )
            observation_gap = not offline.fully_observed

        result.append(
            DeviceSummary(
                id=device.id,  # type: ignore[arg-type]
                address=device.address,
                identifier=device.identifier,
                serial=device.serial,
                display_name=device.display_name,
                product=device.product,
                state=state,  # type: ignore[arg-type]
                recorder_running=running,
                online_since=online_since,
                offline_since=offline_since,
                current_interval_s=current_interval_s,
                last_seen_at=device.last_seen_at,
                observation_gap=observation_gap,
                latest_snapshot_at=snapshot.captured_at if snapshot else None,
                latest_query_status=snapshot.query_status if snapshot else None,
                latest_battery_level=(
                    telemetry_row.battery_level if telemetry_row else None
                ),
                latest_battery_voltage_v=(
                    telemetry_row.battery_voltage_v if telemetry_row else None
                ),
                state_age_s=(
                    max(0, int((now - utc(snapshot.captured_at)).total_seconds()))
                    if snapshot
                    else None
                ),
            )
        )
    return result


def get_device_summary(session: Session, device_id: int) -> DeviceSummary | None:
    for summary in list_device_summaries(session):
        if summary.id == device_id:
            return summary
    return None


def get_device(session: Session, device_id: int) -> Device | None:
    return session.get(Device, device_id)


def get_latest_snapshot(session: Session, device_id: int) -> StateSnapshot | None:
    return session.exec(
        select(StateSnapshot)
        .where(StateSnapshot.device_id == device_id)
        .order_by(StateSnapshot.captured_at.desc(), StateSnapshot.id.desc())
        .limit(1)
    ).first()


def _make_interval(
    *,
    kind: str,
    started_at: dt.datetime,
    ended_at: dt.datetime | None,
    now: dt.datetime,
    from_at: dt.datetime,
    to_at: dt.datetime,
    fully_observed: bool = True,
    start_accuracy: str | None = None,
    query_status: str | None = None,
    scan_count: int | None = None,
) -> PresenceInterval | None:
    effective_end = ended_at or now
    if effective_end < from_at or started_at > to_at:
        return None
    clipped_start = max(started_at, from_at)
    clipped_end = min(effective_end, to_at)
    if clipped_end < clipped_start:
        return None
    return PresenceInterval(
        kind=kind,  # type: ignore[arg-type]
        started_at=started_at,
        ended_at=ended_at,
        duration_s=max(0, int((clipped_end - clipped_start).total_seconds())),
        open=ended_at is None,
        clipped_start=started_at < from_at,
        clipped_end=effective_end > to_at,
        fully_observed=fully_observed,
        start_accuracy=start_accuracy,
        query_status=query_status,
        scan_count=scan_count,
    )


def _collect_intervals(
    session: Session,
    device_id: int,
    from_at: dt.datetime,
    to_at: dt.datetime,
) -> list[PresenceInterval]:
    now = utcnow()
    online = session.exec(
        select(OnlinePeriod)
        .where(OnlinePeriod.device_id == device_id)
        .where(OnlinePeriod.started_at < to_at)
        .where(
            or_(
                OnlinePeriod.ended_at.is_(None),
                OnlinePeriod.ended_at > from_at,
            )
        )
    ).all()
    offline = session.exec(
        select(OffPeriod)
        .where(OffPeriod.device_id == device_id)
        .where(OffPeriod.started_at < to_at)
        .where(
            or_(
                OffPeriod.ended_at.is_(None),
                OffPeriod.ended_at > from_at,
            )
        )
    ).all()

    intervals: list[PresenceInterval] = []
    for period in online:
        item = _make_interval(
            kind="online",
            started_at=period.started_at,
            ended_at=period.ended_at,
            now=now,
            from_at=from_at,
            to_at=to_at,
            query_status=period.query_status,
            scan_count=period.scan_count,
        )
        if item is not None:
            intervals.append(item)
    for period in offline:
        item = _make_interval(
            kind="off",
            started_at=period.started_at,
            ended_at=period.ended_at,
            now=now,
            from_at=from_at,
            to_at=to_at,
            fully_observed=period.fully_observed,
            start_accuracy=period.start_accuracy,
        )
        if item is not None:
            intervals.append(item)
    intervals.sort(key=lambda item: item.started_at)
    return intervals


def presence_history(
    session: Session,
    device_id: int,
    from_at: dt.datetime,
    to_at: dt.datetime,
    *,
    limit: int,
) -> PresenceResponse:
    run = _latest_run(session)
    running = bool(run and run.stopped_at is None)
    intervals = _collect_intervals(session, device_id, from_at, to_at)
    if len(intervals) > limit:
        intervals = intervals[-limit:]

    online_items = [item for item in intervals if item.kind == "online"]
    off_items = [item for item in intervals if item.kind == "off"]
    online_s = sum(item.duration_s for item in online_items)
    off_s = sum(item.duration_s for item in off_items)
    total = online_s + off_s
    found_samples = (
        session.exec(
            select(func.count())
            .select_from(PresenceSample)
            .where(PresenceSample.device_id == device_id)
            .where(PresenceSample.observed_at >= from_at)
            .where(PresenceSample.observed_at < to_at)
        ).one()
        or 0
    )
    summary = PresenceSummary(
        online_s=online_s,
        off_s=off_s,
        uptime_pct=(online_s / total * 100.0) if total else 0.0,
        sessions=len(online_items),
        longest_online_s=max((item.duration_s for item in online_items), default=0),
        longest_off_s=max((item.duration_s for item in off_items), default=0),
        found_samples=int(found_samples),
        observation_gap=any(not item.fully_observed for item in intervals),
    )
    return PresenceResponse(
        device_id=device_id,
        **{"from": from_at, "to": to_at},
        now=utcnow(),
        recorder_running=running,
        intervals=intervals,
        summary=summary,
    )


def presence_samples(
    session: Session,
    device_id: int,
    from_at: dt.datetime,
    to_at: dt.datetime,
    *,
    limit: int,
    offset: int,
) -> PresenceSamplesResponse:
    total = (
        session.exec(
            select(func.count())
            .select_from(PresenceSample)
            .where(PresenceSample.device_id == device_id)
            .where(PresenceSample.observed_at >= from_at)
            .where(PresenceSample.observed_at < to_at)
        ).one()
        or 0
    )
    rows = session.exec(
        select(PresenceSample)
        .where(PresenceSample.device_id == device_id)
        .where(PresenceSample.observed_at >= from_at)
        .where(PresenceSample.observed_at < to_at)
        .order_by(PresenceSample.observed_at.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    items = [
        PresenceSampleDTO(
            observed_at=row.observed_at,
            rssi=row.rssi,
            battery_voltage_adv=row.battery_voltage_adv,
            battery_level=row.battery_level,
        )
        for row in rows
    ]
    return PresenceSamplesResponse(
        total=int(total), limit=limit, offset=offset, items=items
    )


def _bucket_span(bucket: str) -> dt.timedelta:
    if bucket == "hour":
        return HOUR
    if bucket == "day":
        return DAY
    if bucket == "week":
        return DAY * 7
    raise ValueError("bucket must be hour, day or week")


def _bucket_start(value: dt.datetime, bucket: str) -> dt.datetime:
    value = utc(value)
    if bucket == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "week":
        day = value.replace(hour=0, minute=0, second=0, microsecond=0)
        return day - dt.timedelta(days=day.weekday())
    raise ValueError("bucket must be hour, day or week")


def availability_history(
    session: Session,
    device_id: int,
    from_at: dt.datetime,
    to_at: dt.datetime,
    *,
    bucket: str,
    max_points: int,
) -> AvailabilityResponse:
    span = _bucket_span(bucket)
    first = _bucket_start(from_at, bucket)
    if int((to_at - first) / span) + 1 > max_points:
        raise ValueError("requested range produces too many buckets")

    intervals = _collect_intervals(session, device_id, from_at, to_at)
    points: list[AvailabilityPoint] = []
    cursor = first
    while cursor < to_at:
        bucket_end = min(cursor + span, to_at)
        active_start = max(cursor, from_at)
        bucket_seconds = max(0, int((bucket_end - active_start).total_seconds()))
        online_s = 0
        off_s = 0
        for item in intervals:
            item_end = item.ended_at or utcnow()
            overlap_start = max(active_start, item.started_at)
            overlap_end = min(bucket_end, item_end)
            if overlap_end <= overlap_start:
                continue
            seconds = max(0, int((overlap_end - overlap_start).total_seconds()))
            if item.kind == "online":
                online_s += seconds
            else:
                off_s += seconds
        points.append(
            AvailabilityPoint(
                bucket_start=cursor,
                online_s=online_s,
                off_s=off_s,
                unknown_s=max(0, bucket_seconds - online_s - off_s),
            )
        )
        cursor += span
    return AvailabilityResponse(
        device_id=device_id,
        **{"from": from_at, "to": to_at},
        bucket=bucket,
        points=points,
    )


def _json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _value_parts(value: Any) -> tuple[str, str | None, float | None, bool | None]:
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


def _as_dto(model: Any, row: Any) -> Any:
    if row is None:
        return None
    return model.model_validate(row, from_attributes=True)


def _snapshot_written(snapshot: StateSnapshot, image: EepromImage) -> bytearray:
    written = bytearray([1]) * image.length
    for start, end in snapshot.missing_ranges or []:
        offset_start = max(0, start - image.start_address)
        offset_end = min(image.length - 1, end - image.start_address)
        if offset_start <= offset_end:
            written[offset_start : offset_end + 1] = b"\x00" * (
                offset_end - offset_start + 1
            )
    return written


def _parse_snapshot_eeprom(
    session: Session,
    snapshot: StateSnapshot,
    reference_year: int | None = None,
) -> dict[str, Any] | None:
    if snapshot.eeprom_image_id is None:
        return None
    image = session.get(EepromImage, snapshot.eeprom_image_id)
    if image is None:
        return None
    try:
        data = bytes(image.data)
        if image.codec == "zlib":
            data = zlib.decompress(data)
        elif image.codec != "raw":
            logger.warning("Unsupported EEPROM codec %s", image.codec)
            return None
        if reference_year is None and snapshot.device_datetime is not None:
            reference_year = snapshot.device_datetime.year
        return parse_eeprom_image(
            data,
            start_address=image.start_address,
            reference_year=reference_year,
            written=_snapshot_written(snapshot, image),
        )
    except Exception:  # noqa: BLE001 - report a missing parsed state, not a 500
        logger.exception("Could not parse EEPROM for snapshot %s", snapshot.id)
        return None


def _config_from_raw(
    parsed: dict[str, Any], snapshot: StateSnapshot
) -> list[ConfigFieldDTO]:
    items: list[ConfigFieldDTO] = []
    config = parsed.get("config")
    if not isinstance(config, dict):
        return items
    for name, value in config.items():
        field = FIELD_BY_NAME.get(name)
        if field is None:
            continue
        if name in SECRET_FIELD_NAMES:
            value_type, value_text, value_number, value_bool = (
                "redacted",
                "***",
                None,
                None,
            )
        else:
            value_type, value_text, value_number, value_bool = _value_parts(value)
        items.append(
            ConfigFieldDTO(
                name=name,
                address=field.address,
                length=field.length,
                value_type=value_type,
                value_text=value_text,
                value_number=value_number,
                value_bool=value_bool,
                last_seen_at=snapshot.captured_at,
                last_snapshot_id=snapshot.id,
            )
        )
    items.sort(key=lambda item: item.address)
    return items


def _calendar_from_raw(
    parsed: dict[str, Any], snapshot: StateSnapshot
) -> list[CalendarSlotDTO]:
    slots: list[CalendarSlotDTO] = []
    calendar = parsed.get("calendar")
    if not isinstance(calendar, list):
        return slots
    for index, entry in enumerate(calendar):
        mapped = entry.get("bitmask_mapped") or ("", None)
        if isinstance(mapped, (tuple, list)) and len(mapped) == 2:
            mode, days = mapped
        else:
            mode, days = str(mapped), None
        reserved = entry.get("reserved")
        slots.append(
            CalendarSlotDTO(
                slot_index=index,
                bitmask=int(entry.get("bitmask", 0)),
                mode=str(mode),
                days=days,
                hour=int(entry.get("hour", 0)),
                minute=int(entry.get("minute", 0)),
                second=int(entry.get("second", 0)),
                runtime_s=int(entry.get("runtime", 0)),
                reserved_hex=reserved.hex()
                if isinstance(reserved, (bytes, bytearray))
                else None,
            )
        )
    return slots


def _daily_from_raw(
    parsed: dict[str, Any], snapshot: StateSnapshot
) -> list[DailyStatDTO]:
    items: list[DailyStatDTO] = []
    daily = parsed.get("daily_stats")
    if not isinstance(daily, list):
        return items
    for day, stats in daily:
        day_value = day.date() if isinstance(day, dt.datetime) else day
        if not isinstance(day_value, dt.date):
            continue
        items.append(
            DailyStatDTO(
                date=day_value,
                count_normal=stats.get("count-normal"),
                runtime_normal=stats.get("runtime-normal"),
                count_stagnation=stats.get("count-stagnation"),
                runtime_stagnation=stats.get("runtime-stagnation"),
                aerator_lpm=stats.get("aerator-liters-per-minute"),
                consumption_normal_l=stats.get("consumption-normal-liters"),
                consumption_stagnation_l=stats.get("consumption-stagnation-liters"),
                first_seen_at=snapshot.captured_at,
                last_seen_at=snapshot.captured_at,
                last_snapshot_id=snapshot.id,
            )
        )
    return items


def _events_from_raw(
    parsed: dict[str, Any], snapshot: StateSnapshot
) -> list[EventLogDTO]:
    items: list[EventLogDTO] = []
    events = parsed.get("events")
    if not isinstance(events, list):
        return items
    for event in events:
        raw = event.get("raw")
        items.append(
            EventLogDTO(
                id=None,
                log_type=str(event.get("log_type", "unknown")),
                slot_index=int(event.get("slot_index", 0)),
                occurred_at=event.get("occurred_at"),
                status=event.get("status"),
                duration_s=event.get("duration_s"),
                entry_sha256=event.get("entry_sha256"),
                raw_hex=raw.hex() if isinstance(raw, (bytes, bytearray)) else None,
                first_seen_at=snapshot.captured_at,
                last_seen_at=snapshot.captured_at,
                last_snapshot_id=snapshot.id,
            )
        )
    items.sort(
        key=lambda item: (
            item.occurred_at is None,
            item.occurred_at or dt.datetime.min,
        )
    )
    return items


def _config_from_db(session: Session, device_id: int) -> list[ConfigFieldDTO]:
    rows = session.exec(
        select(ConfigFieldValue)
        .where(ConfigFieldValue.device_id == device_id)
        .order_by(ConfigFieldValue.name)
    ).all()
    return [
        ConfigFieldDTO(
            name=row.name,
            address=row.address,
            length=row.length,
            value_type=row.value_type,
            value_text=row.value_text,
            value_number=row.value_number,
            value_bool=row.value_bool,
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            last_snapshot_id=row.last_snapshot_id,
        )
        for row in rows
    ]


def _calendar_from_db(session: Session, device_id: int) -> list[CalendarSlotDTO]:
    rows = session.exec(
        select(CalendarSlot)
        .where(CalendarSlot.device_id == device_id)
        .order_by(CalendarSlot.slot_index)
    ).all()
    return [
        CalendarSlotDTO(
            slot_index=row.slot_index,
            bitmask=row.bitmask,
            mode=row.mode,
            days=row.days,
            hour=row.hour,
            minute=row.minute,
            second=row.second,
            runtime_s=row.runtime_s,
        )
        for row in rows
    ]


def _daily_from_db(session: Session, device_id: int) -> list[DailyStatDTO]:
    rows = session.exec(
        select(DailyStat)
        .where(DailyStat.device_id == device_id)
        .order_by(DailyStat.stat_date)
    ).all()
    return [
        DailyStatDTO(
            date=row.stat_date,
            count_normal=row.count_normal,
            runtime_normal=row.runtime_normal,
            count_stagnation=row.count_stagnation,
            runtime_stagnation=row.runtime_stagnation,
            aerator_lpm=row.aerator_lpm,
            consumption_normal_l=row.consumption_normal_l,
            consumption_stagnation_l=row.consumption_stagnation_l,
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            last_snapshot_id=row.last_snapshot_id,
        )
        for row in rows
    ]


def _events_from_db(
    session: Session, device_id: int, limit: int = 200
) -> list[EventLogDTO]:
    rows = session.exec(
        select(EventLogEntry)
        .where(EventLogEntry.device_id == device_id)
        .order_by(
            func.coalesce(
                EventLogEntry.occurred_at, EventLogEntry.first_seen_at
            ).desc()
        )
        .limit(limit)
    ).all()
    return [
        EventLogDTO(
            id=row.id,
            log_type=row.log_type,
            slot_index=row.slot_index,
            occurred_at=row.occurred_at,
            status=row.status,
            duration_s=row.duration_s,
            entry_sha256=row.entry_sha256,
            raw_hex=bytes(row.raw).hex(),
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            last_snapshot_id=row.last_snapshot_id,
        )
        for row in rows
    ]


def load_snapshot_state(
    session: Session,
    device: DeviceSummary,
    snapshot: StateSnapshot | None,
) -> SnapshotStateResponse:
    if snapshot is None:
        return SnapshotStateResponse(device=device, snapshot=None)

    telemetry = _as_dto(TelemetryDTO, session.get(TelemetryState, snapshot.id))
    firmware = _as_dto(FirmwareDTO, session.get(FirmwareState, snapshot.id))
    module_info = _as_dto(ModuleInfoDTO, session.get(ModuleInfoState, snapshot.id))
    lifetime = _as_dto(LifetimeStatsDTO, session.get(LifetimeStatsState, snapshot.id))
    today = _as_dto(TodayStatsDTO, session.get(TodayStatsState, snapshot.id))
    eeprom = _eeprom_meta(session, snapshot.eeprom_image_id)
    reference_year = (
        telemetry.device_datetime.year
        if telemetry is not None and telemetry.device_datetime is not None
        else None
    )
    parsed = _parse_snapshot_eeprom(session, snapshot, reference_year)

    if parsed is not None:
        config = _config_from_raw(parsed, snapshot)
        calendar = _calendar_from_raw(parsed, snapshot)
        daily = _daily_from_raw(parsed, snapshot)
        events = _events_from_raw(parsed, snapshot)
        source = "eeprom"
    else:
        config = _config_from_db(session, device.id)
        calendar = _calendar_from_db(session, device.id)
        daily = _daily_from_db(session, device.id)
        events = _events_from_db(session, device.id)
        source = "current_tables"

    return SnapshotStateResponse(
        device=device,
        snapshot=_snapshot_summary(snapshot, eeprom),
        state_source=source,
        telemetry=telemetry,
        firmware=firmware,
        module_info=module_info,
        lifetime=lifetime,
        today=today,
        config=config,
        calendar=calendar,
        daily_stats=daily,
        events=events,
    )


def current_state(
    session: Session, device_id: int
) -> SnapshotStateResponse | None:
    device = get_device_summary(session, device_id)
    if device is None:
        return None
    snapshot = get_latest_snapshot(session, device_id)
    return load_snapshot_state(session, device, snapshot)


def get_snapshot(
    session: Session, device_id: int, snapshot_id: int
) -> StateSnapshot | None:
    snapshot = session.get(StateSnapshot, snapshot_id)
    if snapshot is None or snapshot.device_id != device_id:
        return None
    return snapshot


def list_snapshots(
    session: Session,
    device_id: int,
    *,
    from_at: dt.datetime | None,
    to_at: dt.datetime | None,
    limit: int,
    offset: int,
) -> SnapshotListResponse:
    conditions = [StateSnapshot.device_id == device_id]
    if from_at is not None:
        conditions.append(StateSnapshot.captured_at >= from_at)
    if to_at is not None:
        conditions.append(StateSnapshot.captured_at < to_at)
    total = (
        session.exec(
            select(func.count())
            .select_from(StateSnapshot)
            .where(*conditions)
        ).one()
        or 0
    )
    rows = session.exec(
        select(StateSnapshot)
        .where(*conditions)
        .order_by(StateSnapshot.captured_at.desc(), StateSnapshot.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    image_ids = [
        row.eeprom_image_id for row in rows if row.eeprom_image_id is not None
    ]
    images = (
        session.exec(select(EepromImage).where(EepromImage.id.in_(image_ids))).all()
        if image_ids
        else []
    )
    image_map = {row.id: row for row in images}
    items = []
    for row in rows:
        image = image_map.get(row.eeprom_image_id)
        meta = (
            EepromMeta(
                sha256=image.sha256,
                start_address=image.start_address,
                length=image.length,
                coverage=image.coverage,
                codec=image.codec,
                first_seen_at=image.first_seen_at,
                last_seen_at=image.last_seen_at,
                seen_count=image.seen_count,
            )
            if image
            else None
        )
        items.append(_snapshot_summary(row, meta))
    return SnapshotListResponse(
        total=int(total), limit=limit, offset=offset, items=items
    )


def load_raw_eeprom(session: Session, snapshot: StateSnapshot) -> bytes | None:
    if snapshot.eeprom_image_id is None:
        return None
    image = session.get(EepromImage, snapshot.eeprom_image_id)
    if image is None:
        return None
    data = bytes(image.data)
    if image.codec == "zlib":
        return zlib.decompress(data)
    if image.codec == "raw":
        return data
    return None


def _average(values: list[float | int | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def telemetry_history(
    session: Session,
    device_id: int,
    from_at: dt.datetime,
    to_at: dt.datetime,
    *,
    bucket: str,
    limit: int,
) -> TelemetryHistoryResponse:
    if bucket not in {"raw", "hour", "day", "week"}:
        raise ValueError("bucket must be raw, hour, day or week")
    rows = session.exec(
        select(StateSnapshot, TelemetryState)
        .join(TelemetryState, TelemetryState.snapshot_id == StateSnapshot.id)
        .where(StateSnapshot.device_id == device_id)
        .where(StateSnapshot.captured_at >= from_at)
        .where(StateSnapshot.captured_at < to_at)
        .order_by(StateSnapshot.captured_at.asc())
    ).all()
    points = [
        TelemetryPoint(
            captured_at=snapshot.captured_at,
            device_datetime=telemetry.device_datetime,
            battery_voltage_v=telemetry.battery_voltage_v,
            battery_level=telemetry.battery_level,
            vcc_v=telemetry.vcc_v,
            temperature_raw=telemetry.temperature_raw,
            rail_33_raw=telemetry.rail_33_raw,
        )
        for snapshot, telemetry in rows
    ]
    if bucket == "raw":
        if len(points) > limit:
            raise ValueError("too many telemetry points; use a bucket")
    else:
        buckets: dict[dt.datetime, list[TelemetryPoint]] = defaultdict(list)
        for point in points:
            buckets[_bucket_start(point.captured_at, bucket)].append(point)
        points = [
            TelemetryPoint(
                captured_at=start,
                device_datetime=next(
                    (
                        item.device_datetime
                        for item in reversed(items)
                        if item.device_datetime is not None
                    ),
                    None,
                ),
                battery_voltage_v=_average([item.battery_voltage_v for item in items]),
                battery_level=int(_average([item.battery_level for item in items]) or 0)
                if any(item.battery_level is not None for item in items)
                else None,
                vcc_v=_average([item.vcc_v for item in items]),
                temperature_raw=int(_average([item.temperature_raw for item in items]) or 0)
                if any(item.temperature_raw is not None for item in items)
                else None,
                rail_33_raw=int(_average([item.rail_33_raw for item in items]) or 0)
                if any(item.rail_33_raw is not None for item in items)
                else None,
                samples=len(items),
            )
            for start, items in sorted(buckets.items())
        ]
    return TelemetryHistoryResponse(
        device_id=device_id,
        **{"from": from_at, "to": to_at},
        bucket=bucket,
        points=points,
    )


def counter_history(
    session: Session,
    device_id: int,
    from_at: dt.datetime,
    to_at: dt.datetime,
) -> CounterHistoryResponse:
    snapshots = session.exec(
        select(StateSnapshot)
        .where(StateSnapshot.device_id == device_id)
        .where(StateSnapshot.captured_at >= from_at)
        .where(StateSnapshot.captured_at < to_at)
        .order_by(StateSnapshot.captured_at.asc())
    ).all()
    if not snapshots:
        return CounterHistoryResponse(
            device_id=device_id, **{"from": from_at, "to": to_at}, points=[]
        )
    ids = [snapshot.id for snapshot in snapshots if snapshot.id is not None]
    today_rows = session.exec(
        select(TodayStatsState).where(TodayStatsState.snapshot_id.in_(ids))
    ).all()
    lifetime_rows = session.exec(
        select(LifetimeStatsState).where(LifetimeStatsState.snapshot_id.in_(ids))
    ).all()
    today_map = {row.snapshot_id: row for row in today_rows}
    lifetime_map = {row.snapshot_id: row for row in lifetime_rows}
    points: list[CounterPoint] = []
    for snapshot in snapshots:
        today = today_map.get(snapshot.id)
        lifetime = lifetime_map.get(snapshot.id)
        if today is None and lifetime is None:
            continue
        points.append(
            CounterPoint(
                captured_at=snapshot.captured_at,
                device_datetime=snapshot.device_datetime,
                count_normal=today.count_normal if today else None,
                runtime_normal=today.runtime_normal if today else None,
                count_stagnation=today.count_stagnation if today else None,
                runtime_stagnation=today.runtime_stagnation if today else None,
                consumption_normal_l=today.consumption_normal_l if today else None,
                consumption_stagnation_l=(
                    today.consumption_stagnation_l if today else None
                ),
                count_restart=lifetime.count_restart if lifetime else None,
                count_lifetime=lifetime.count_lifetime if lifetime else None,
            )
        )
    return CounterHistoryResponse(
        device_id=device_id, **{"from": from_at, "to": to_at}, points=points
    )


def daily_stats_history(
    session: Session,
    device_id: int,
    *,
    from_date: dt.date | None,
    to_date: dt.date | None,
) -> DailyStatsResponse:
    conditions = [DailyStat.device_id == device_id]
    if from_date is not None:
        conditions.append(DailyStat.stat_date >= from_date)
    if to_date is not None:
        conditions.append(DailyStat.stat_date <= to_date)
    rows = session.exec(
        select(DailyStat).where(*conditions).order_by(DailyStat.stat_date.asc())
    ).all()
    items = [
        DailyStatDTO(
            date=row.stat_date,
            count_normal=row.count_normal,
            runtime_normal=row.runtime_normal,
            count_stagnation=row.count_stagnation,
            runtime_stagnation=row.runtime_stagnation,
            aerator_lpm=row.aerator_lpm,
            consumption_normal_l=row.consumption_normal_l,
            consumption_stagnation_l=row.consumption_stagnation_l,
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            last_snapshot_id=row.last_snapshot_id,
        )
        for row in rows
    ]
    return DailyStatsResponse(
        device_id=device_id,
        from_date=from_date,
        to_date=to_date,
        items=items,
    )


def event_history(
    session: Session,
    device_id: int,
    *,
    log_type: str | None,
    from_at: dt.datetime | None,
    to_at: dt.datetime | None,
    limit: int,
    offset: int,
) -> EventHistoryResponse:
    timestamp = func.coalesce(EventLogEntry.occurred_at, EventLogEntry.first_seen_at)
    conditions = [EventLogEntry.device_id == device_id]
    if log_type:
        conditions.append(EventLogEntry.log_type == log_type)
    if from_at is not None:
        conditions.append(timestamp >= from_at)
    if to_at is not None:
        conditions.append(timestamp < to_at)
    total = (
        session.exec(
            select(func.count())
            .select_from(EventLogEntry)
            .where(*conditions)
        ).one()
        or 0
    )
    rows = session.exec(
        select(EventLogEntry)
        .where(*conditions)
        .order_by(timestamp.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    items = [
        EventLogDTO(
            id=row.id,
            log_type=row.log_type,
            slot_index=row.slot_index,
            occurred_at=row.occurred_at,
            status=row.status,
            duration_s=row.duration_s,
            entry_sha256=row.entry_sha256,
            raw_hex=bytes(row.raw).hex(),
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            last_snapshot_id=row.last_snapshot_id,
        )
        for row in rows
    ]
    return EventHistoryResponse(
        total=int(total), limit=limit, offset=offset, items=items
    )


def config_changes(
    session: Session,
    device_id: int,
    *,
    name: str | None,
    from_at: dt.datetime | None,
    to_at: dt.datetime | None,
    limit: int,
) -> list[ConfigChangeDTO]:
    conditions = [ConfigChange.device_id == device_id]
    if name:
        conditions.append(ConfigChange.name == name)
    if from_at is not None:
        conditions.append(ConfigChange.changed_at >= from_at)
    if to_at is not None:
        conditions.append(ConfigChange.changed_at < to_at)
    rows = session.exec(
        select(ConfigChange)
        .where(*conditions)
        .order_by(ConfigChange.changed_at.desc())
        .limit(limit)
    ).all()
    return [
        ConfigChangeDTO(
            id=row.id,  # type: ignore[arg-type]
            name=row.name,
            changed_at=row.changed_at,
            old_value_text=row.old_value_text,
            new_value_text=row.new_value_text,
            old_value_number=row.old_value_number,
            new_value_number=row.new_value_number,
            snapshot_id=row.snapshot_id,
        )
        for row in rows
    ]


def recorder_runs(session: Session, limit: int) -> list[RecorderRun]:
    return list(
        session.exec(
            select(RecorderRun)
            .order_by(RecorderRun.started_at.desc())
            .limit(limit)
        ).all()
    )


def compare_snapshots(
    session: Session,
    device_id: int,
    base_snapshot_id: int,
    target_snapshot_id: int,
) -> CompareResponse | None:
    device = get_device_summary(session, device_id)
    base_snapshot = get_snapshot(session, device_id, base_snapshot_id)
    target_snapshot = get_snapshot(session, device_id, target_snapshot_id)
    if device is None or base_snapshot is None or target_snapshot is None:
        return None

    base = load_snapshot_state(session, device, base_snapshot)
    target = load_snapshot_state(session, device, target_snapshot)
    if base.state_source != "eeprom" or target.state_source != "eeprom":
        raise ValueError("both snapshots need a stored EEPROM image to compare")

    base_config = {item.name: item for item in base.config}
    target_config = {item.name: item for item in target.config}
    config_changes: list[ConfigFieldChange] = []
    for name in sorted(set(base_config) | set(target_config)):
        old = base_config.get(name)
        new = target_config.get(name)
        old_value = (
            (old.value_text, old.value_number, old.value_bool) if old else None
        )
        new_value = (
            (new.value_text, new.value_number, new.value_bool) if new else None
        )
        if old_value != new_value:
            config_changes.append(
                ConfigFieldChange(
                    name=name,
                    base_value=old.value_text if old else None,
                    target_value=new.value_text if new else None,
                )
            )

    telemetry_fields = (
        "battery_voltage_v",
        "battery_level",
        "vcc_v",
        "temperature_raw",
        "rail_33_raw",
    )
    telemetry_changes: dict[str, Any] = {}
    for field in telemetry_fields:
        old_value = getattr(base.telemetry, field, None) if base.telemetry else None
        new_value = getattr(target.telemetry, field, None) if target.telemetry else None
        if old_value != new_value:
            telemetry_changes[field] = {"base": old_value, "target": new_value}

    counter_fields = (
        "count_normal",
        "runtime_normal",
        "count_stagnation",
        "runtime_stagnation",
        "consumption_normal_l",
        "consumption_stagnation_l",
        "count_restart",
        "count_lifetime",
    )
    counter_changes: dict[str, Any] = {}
    for field in counter_fields:
        old_value = getattr(base.today, field, None) if base.today else None
        new_value = getattr(target.today, field, None) if target.today else None
        if field in {"count_restart", "count_lifetime"}:
            old_value = getattr(base.lifetime, field, None) if base.lifetime else None
            new_value = (
                getattr(target.lifetime, field, None) if target.lifetime else None
            )
        if old_value != new_value:
            counter_changes[field] = {"base": old_value, "target": new_value}

    daily_fields = (
        "count_normal",
        "runtime_normal",
        "count_stagnation",
        "runtime_stagnation",
        "aerator_lpm",
        "consumption_normal_l",
        "consumption_stagnation_l",
    )
    base_daily = {item.date: item for item in base.daily_stats}
    target_daily = {item.date: item for item in target.daily_stats}
    daily_changes: list[dict[str, Any]] = []
    for day in sorted(set(base_daily) | set(target_daily)):
        old = base_daily.get(day)
        new = target_daily.get(day)
        changed: dict[str, Any] = {}
        for field in daily_fields:
            old_value = getattr(old, field, None) if old else None
            new_value = getattr(new, field, None) if new else None
            if old_value != new_value:
                changed[field] = {"base": old_value, "target": new_value}
        if changed:
            daily_changes.append({"date": day.isoformat(), "changes": changed})

    base_events = {
        item.entry_sha256 or f"{item.log_type}:{item.slot_index}:{item.raw_hex}"
        for item in base.events
    }
    target_events = {
        item.entry_sha256 or f"{item.log_type}:{item.slot_index}:{item.raw_hex}"
        for item in target.events
    }
    new_events = [
        item
        for item in target.events
        if (item.entry_sha256 or f"{item.log_type}:{item.slot_index}:{item.raw_hex}")
        not in base_events
    ]
    removed_events = [
        item
        for item in base.events
        if (item.entry_sha256 or f"{item.log_type}:{item.slot_index}:{item.raw_hex}")
        not in target_events
    ]

    return CompareResponse(
        device_id=device_id,
        base_snapshot_id=base_snapshot_id,
        target_snapshot_id=target_snapshot_id,
        config_changes=config_changes,
        telemetry_changes=telemetry_changes,
        counter_changes=counter_changes,
        daily_changes=daily_changes,
        new_events=new_events,
        removed_events=removed_events,
    )