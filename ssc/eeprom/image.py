"""Parsing of an assembled full EEPROM image.

The normal notification parser sees 16-byte chunks, so a field that spans a
chunk boundary (notably the 112-byte calendar) cannot be decoded there.  Once
the recorder has assembled the complete image, this module extracts every
known field, the event logs and the daily statistics in one pass.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from typing import Any

from ssc.codecs import chunk_bytes
from ssc.eeprom.daily_stats import parse_daily_stats
from ssc.eeprom.event_history import EVENT_CHUNK_SIZE, parse_event_history_chunk
from ssc.eeprom.layout import FIELDS
from ssc.eeprom.regions import (
    DAILY_STATS_END,
    DAILY_STATS_START,
    LOG_REGIONS,
)

logger = logging.getLogger(__name__)

CALENDAR_FIELD_NAME = "EEPROM_CalendarStart"


def _is_written(
    written: bytes | bytearray | None,
    start_address: int,
    address: int,
    length: int,
) -> bool:
    if written is None:
        return True
    offset = address - start_address
    if offset < 0 or offset + length > len(written):
        return False
    return all(written[offset:offset + length])


def parse_eeprom_image(
    image: bytes,
    *,
    start_address: int = 0,
    reference_year: int | None = None,
    written: bytes | bytearray | None = None,
) -> dict[str, Any]:
    """Decode all known structures from a full EEPROM image.

    ``written`` optionally marks which bytes were actually received, so fields
    that overlap a missing range are reported as missing instead of being
    decoded from ``0xFF`` filler.
    """
    config: dict[str, object] = {}
    missing_fields: list[str] = []

    for field in FIELDS:
        if field.address < start_address:
            continue
        if not _is_written(written, start_address, field.address, field.length):
            missing_fields.append(field.name)
            continue
        offset = field.address - start_address
        if offset + field.length > len(image):
            missing_fields.append(field.name)
            continue
        segment = image[offset:offset + field.length]
        try:
            config[field.name] = field.loads(segment)
        except Exception as exc:  # noqa: BLE001 - one bad field must not abort the dump
            logger.debug("Could not parse %s: %s", field.name, exc)
            missing_fields.append(field.name)

    calendar = config.pop(CALENDAR_FIELD_NAME, [])
    if not isinstance(calendar, list):
        calendar = []

    events: list[dict[str, Any]] = []
    for region_start, region_end, log_type in LOG_REGIONS:
        region_length = region_end - region_start + 1
        if not _is_written(written, start_address, region_start, region_length):
            continue
        region = _slice(image, start_address, region_start, region_length)
        if region is None:
            continue
        for index, raw in enumerate(chunk_bytes(region, EVENT_CHUNK_SIZE)):
            if len(raw) != EVENT_CHUNK_SIZE:
                continue
            entry = parse_event_history_chunk(raw)
            if not _valid_event(entry):
                continue
            occurred_at = _event_datetime(entry)
            events.append(
                {
                    "log_type": log_type,
                    "slot_index": index,
                    "occurred_at": occurred_at,
                    "status": entry.get("status"),
                    "duration_s": entry.get("duration"),
                    "entry_sha256": hashlib.sha256(raw).hexdigest(),
                    "raw": raw,
                    "is_valid": occurred_at is not None,
                }
            )

    daily_length = DAILY_STATS_END - DAILY_STATS_START + 1
    daily_complete = _is_written(
        written, start_address, DAILY_STATS_START, daily_length
    )
    daily_region = (
        _slice(image, start_address, DAILY_STATS_START, daily_length)
        if daily_complete
        else None
    )
    daily_stats = (
        parse_daily_stats(
            daily_region,
            DAILY_STATS_START,
            reference_year=reference_year,
        )
        if daily_region is not None
        else []
    )

    return {
        "config": config,
        "calendar": calendar,
        "events": events,
        "daily_stats": daily_stats,
        "missing_fields": missing_fields,
    }


def _slice(
    image: bytes,
    start_address: int,
    address: int,
    length: int,
) -> bytes | None:
    offset = address - start_address
    if offset < 0 or offset + length > len(image):
        return None
    return image[offset:offset + length]


def _valid_event(entry: dict[str, object]) -> bool:
    month = entry.get("month")
    day = entry.get("day")
    year = entry.get("year")
    if not isinstance(month, int) or not isinstance(day, int) or not isinstance(year, int):
        return False
    if month == 0 or month > 12 or day == 0 or day > 31:
        return False
    return True


def _event_datetime(entry: dict[str, object]) -> dt.datetime | None:
    values = (
        entry.get("year"),
        entry.get("month"),
        entry.get("day"),
        entry.get("hour"),
        entry.get("minute"),
        entry.get("second"),
    )
    if not all(isinstance(value, int) for value in values):
        return None
    try:
        return dt.datetime(*values)  # type: ignore[arg-type]
    except ValueError:
        return None