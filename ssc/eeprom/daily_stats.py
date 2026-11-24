"""Daily consumption statistics stored in the EEPROM (address 0x0A00..0x1569)."""

from __future__ import annotations

import datetime
import logging

from ssc.codecs import chunk_bytes
from ssc.eeprom.regions import DAILY_STATS_BASE, DAILY_STATS_STRIDE
from ssc.stats import STAT_CHUNK_SIZE, parse_stats_chunk
from ssc.types import ConsumptionStats

logger = logging.getLogger(__name__)


def date_from_address(
    address: int,
    reference_year: int | None = None,
) -> datetime.datetime:
    """Map a daily stats address to the day it stores.

    The EEPROM stores a day-of-year offset but no year.  The device RTC year
    should be passed as *reference_year*; otherwise the host's current year is
    used as a fallback.
    """
    day_of_year_0_based = (address - DAILY_STATS_BASE) // DAILY_STATS_STRIDE
    year = reference_year or datetime.datetime.now().year
    return datetime.datetime(year, 1, 1) + datetime.timedelta(days=day_of_year_0_based)


def parse_today_stats(data: bytes) -> ConsumptionStats:
    """Decode today's counters (array index 0x0B)."""
    if len(data) > STAT_CHUNK_SIZE:
        logger.warning("Warning: data length for today's stats is greater than 8 bytes")
    return parse_stats_chunk(data, today_variant=True)


def parse_daily_stats(
    data: bytes,
    address: int,
    reference_year: int | None = None,
) -> list[tuple[datetime.datetime, ConsumptionStats]]:
    """Decode a run of daily chunks, starting at EEPROM *address*."""
    stats: list[tuple[datetime.datetime, ConsumptionStats]] = []
    for index, chunk in enumerate(chunk_bytes(data, STAT_CHUNK_SIZE)):
        if len(chunk) != STAT_CHUNK_SIZE:
            logger.debug("Ignoring incomplete daily stats chunk at index %s", index)
            continue
        stats.append(
            (
                date_from_address(
                    address + index * STAT_CHUNK_SIZE,
                    reference_year=reference_year,
                ),
                parse_stats_chunk(chunk),
            )
        )
    return stats