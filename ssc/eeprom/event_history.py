"""Decoding of the event history logs (address 0x0400..0x09FF).

Each log entry occupies 8 bytes::

    [0]    year (raw, add 2000)
    [1]    mode (high nibble) + month (low nibble)
    [2]    status (high nibble) + day (low nibble)
    [3]    hour
    [4]    minute
    [5]    second
    [6..7] duration in seconds (uint16 LE)
"""

from __future__ import annotations

from ssc.codecs import chunk_bytes
from ssc.eeprom.regions import classify_logtype

EVENT_CHUNK_SIZE = 8
EVENT_YEAR_OFFSET = 2000
STATUS_OK = 0


def parse_event_history_chunk_raw(chunk: bytes) -> dict[str, int]:
    """Extract the raw fields of one event log entry."""
    return {
        "year_raw": chunk[0],
        "mode_raw": (chunk[1] & 0b11110000) >> 4,
        "month": chunk[1] & 0b00001111,
        "status_raw": (chunk[2] & 0b11110000) >> 4,
        "day": chunk[2] & 0b00001111,
        "hour": chunk[3],
        "minute": chunk[4],
        "second": chunk[5],
        "duration": int.from_bytes(chunk[6:8], byteorder="little"),
    }


def map_log_entry_status(status_raw: int) -> str:
    """Map the status nibble to a readable label."""
    return "success" if status_raw == STATUS_OK else "error/interrupted"


def calculate_log_entry_year(year_raw: int) -> int:
    """Add the century offset to the raw year byte."""
    return EVENT_YEAR_OFFSET + year_raw


def parse_event_history_chunk(chunk: bytes) -> dict[str, object]:
    """Decode one event log entry with derived year and status."""
    entry: dict[str, object] = parse_event_history_chunk_raw(chunk)
    entry["year"] = calculate_log_entry_year(entry["year_raw"])
    entry["status"] = map_log_entry_status(entry["status_raw"])
    return entry


def parse_event_history(data: bytes, address: int) -> dict[str, object]:
    """Decode a run of event log entries, starting at EEPROM *address*."""
    return {
        "logtype": classify_logtype(address),
        "entries": [
            parse_event_history_chunk(chunk)
            for chunk in chunk_bytes(data, EVENT_CHUNK_SIZE)
        ],
    }