"""Decoding of consumption statistics.

Two sources use the same 8 byte chunk layout:

* array index ``0x06`` (lifetime counters, ``CMD_READ_ARRAY``)
* array index ``0x0B`` (today's counters).  Here the two 16 bit counters are
  big endian, so the first four bytes have to be swapped before parsing.
"""

from __future__ import annotations

import logging

from ssc.types import ConsumptionStats, LifetimeStats

logger = logging.getLogger(__name__)

STAT_CHUNK_SIZE = 8
SENTINEL_16 = 0xFFFF
SENTINEL_8 = 0xFF

STAT_16BIT_KEYS = ("count-normal", "runtime-normal", "runtime-stagnation")
STAT_8BIT_KEYS = ("count-stagnation", "aerator-liters-per-minute")


def parse_stats_raw(data: bytes) -> ConsumptionStats:
    """Extract the raw counters of one stats chunk."""
    if len(data) < STAT_CHUNK_SIZE:
        raise ValueError(
            f"Stats chunk must be {STAT_CHUNK_SIZE} bytes, got {len(data)}"
        )
    return {
        "count-normal": int.from_bytes(data[0:2], byteorder="little"),
        "runtime-normal": int.from_bytes(data[2:4], byteorder="little"),
        "count-stagnation": data[4],
        "runtime-stagnation": int.from_bytes(data[5:7], byteorder="little"),
        "aerator-liters-per-minute": data[7],
    }


def normalize_stats(stats: ConsumptionStats) -> ConsumptionStats:
    """Replace the "not set" sentinel values with zero."""
    for key in STAT_16BIT_KEYS:
        if stats[key] == SENTINEL_16:
            stats[key] = 0
    for key in STAT_8BIT_KEYS:
        if stats[key] == SENTINEL_8:
            stats[key] = 0
    return stats


def calculate_stats(stats: ConsumptionStats) -> ConsumptionStats:
    """Derive the consumed liters from runtime and aerator flow rate."""
    stats["consumption-normal-liters"] = (
        stats["runtime-normal"] / 60
    ) * stats["aerator-liters-per-minute"]
    stats["consumption-stagnation-liters"] = (
        stats["runtime-stagnation"] / 60
    ) * stats["aerator-liters-per-minute"]
    return stats


def apply_today_variant(data: bytes) -> bytes:
    """Swap the two leading big endian 16 bit counters of a "today" chunk."""
    if len(data) < 4:
        raise ValueError("Data too short for today variant")
    result = bytearray(data)
    result[0], result[1] = data[1], data[0]
    result[2], result[3] = data[3], data[2]
    return bytes(result)


def parse_stats_chunk(data: bytes, today_variant: bool = False) -> ConsumptionStats:
    """Decode one 8 byte stats chunk."""
    logger.debug("Original stats data: %s", data.hex(" "))
    if today_variant:
        data = apply_today_variant(data)
    stats = parse_stats_raw(data)
    stats = normalize_stats(stats)
    return calculate_stats(stats)


def parse_lifetime_stats(data: bytes) -> LifetimeStats:
    """Decode the lifetime counters (array index 0x06)."""
    logger.debug("Lifetime stats data: %s", data.hex(" "))
    if len(data) < 8:
        raise ValueError(f"Lifetime stats must be 8 bytes, got {len(data)}")
    return {
        "count-restart": int.from_bytes(data[0:4], byteorder="little"),
        "count-lifetime": int.from_bytes(data[4:8], byteorder="little"),
    }