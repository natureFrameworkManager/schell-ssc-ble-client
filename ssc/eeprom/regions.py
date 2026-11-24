"""Address map of the EEPROM.

The device exposes a 64 KiB EEPROM, but not every range has the same meaning.
``classify_address`` tells the notification parser how to decode a read
response, and ``classify_logtype`` separates the four event logs that share the
event history region.
"""

from __future__ import annotations

from enum import Enum

CONFIG_END = 0x03FF
EVENT_HISTORY_START = 0x0400
EVENT_HISTORY_END = 0x09FF
DAILY_STATS_START = 0x0A00
DAILY_STATS_END = 0x1569

# Daily stats: one 8 byte chunk per day, starting at address 2560 (day offset 0).
DAILY_STATS_BASE = 2560
DAILY_STATS_STRIDE = 8

LOG_REGIONS: tuple[tuple[int, int, str], ...] = (
    (1024, 2047, "stagnation flush"),
    (2048, 2175, "thermal desinfection"),
    (2176, 2303, "dauerlauf"),
    (2304, 2431, "cleaning stop"),
)

UNKNOWN_LOG_TYPE = "unknown"


class EepromRegion(Enum):
    """Semantic regions of the EEPROM address space."""

    CONFIG = "config"
    EVENT_HISTORY = "event history"
    DAILY_STATS = "daily stats"


def classify_address(address: int) -> EepromRegion | None:
    """Return the region *address* belongs to, or ``None`` if unassigned."""
    if 0 <= address <= CONFIG_END:
        return EepromRegion.CONFIG
    if EVENT_HISTORY_START <= address <= EVENT_HISTORY_END:
        return EepromRegion.EVENT_HISTORY
    if DAILY_STATS_START <= address <= DAILY_STATS_END:
        return EepromRegion.DAILY_STATS
    return None


def classify_logtype(address: int) -> str:
    """Return the name of the event log stored at *address*."""
    for start, end, name in LOG_REGIONS:
        if start <= address <= end:
            return name
    return UNKNOWN_LOG_TYPE