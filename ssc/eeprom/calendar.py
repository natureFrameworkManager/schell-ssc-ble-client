"""Decoding of the weekly irrigation calendar block.

The calendar occupies 112 bytes, i.e. 14 chunks of 8 bytes.  Chunk layout::

    [0]     bitmask: bit0=Mon .. bit6=Sun (scheduled mode);
            0x7F = "need-based" sentinel; 0xFF = empty/disabled slot
    [1]     hour (0-23)
    [2]     minute
    [3]     second
    [4..5]  runtime in seconds (uint16 LE)
    [6..7]  reserved (0xFF 0xFF)
"""

from __future__ import annotations

from ssc.codecs import chunk_bytes
from ssc.types import CalendarChunk, CalendarEntry

CALENDAR_CHUNK_SIZE = 8
BITMASK_NEED_BASED = 0x7F
BITMASK_EMPTY = 0xFF
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def split_calendar(data: bytes) -> list[bytes]:
    """Split the calendar block into its 8 byte chunks."""
    return chunk_bytes(data, CALENDAR_CHUNK_SIZE)


def parse_calendar_chunk(data: bytes) -> CalendarChunk:
    """Parse a single 8 byte calendar chunk."""
    if len(data) != CALENDAR_CHUNK_SIZE:
        raise ValueError("Calendar chunk must be 8 bytes")
    return {
        "bitmask": data[0],
        "hour": data[1],
        "minute": data[2],
        "second": data[3],
        "runtime": int.from_bytes(data[4:6], "little"),
        "reserved": data[6:8],
    }


def map_calendar_bitmask(bitmask_raw: int) -> tuple[str, str | None]:
    """Turn the calendar bitmask into ``(mode, active days)``."""
    if bitmask_raw == BITMASK_NEED_BASED:
        return ("Need-based", None)
    if bitmask_raw == BITMASK_EMPTY:
        return ("Empty", None)
    active_days = [day for index, day in enumerate(DAY_NAMES) if bitmask_raw & (1 << index)]
    return ("Scheduled", ", ".join(active_days) if active_days else None)


def parse_calendar(data: bytes) -> list[CalendarEntry]:
    """Decode the complete calendar block."""
    chunks = [parse_calendar_chunk(chunk) for chunk in split_calendar(data)]
    return [
        {**chunk, "bitmask_mapped": map_calendar_bitmask(chunk["bitmask"])}
        for chunk in chunks
    ]