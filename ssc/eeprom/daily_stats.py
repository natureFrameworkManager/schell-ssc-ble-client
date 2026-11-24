"""Daily consumption statistics stored in the EEPROM (address 0x0A00..0x1569)."""

from __future__ import annotations

import datetime
import logging

from ssc.codecs import chunk_bytes
from ssc.eeprom.regions import DAILY_STATS_BASE, DAILY_STATS_STRIDE
from ssc.stats import STAT_CHUNK_SIZE, parse_stats_chunk
from ssc.types import ConsumptionStats

logger = logging.getLogger(__name__)


def date_from_address(address: int) -> datetime.datetime:
    """Map a daily stats address to the day it stores."""
    day_of_year_0_based = (address - DAILY_STATS_BASE) // DAILY_STATS_STRIDE
    current_year = datetime.datetime.now().year
    return datetime.datetime(current_year, 1, 1) + datetime.timedelta(days=day_of_year_0_based)


def parse_today_stats(data: bytes) -> ConsumptionStats:
    """Decode today's counters (array index 0x0B)."""
    if len(data) > STAT_CHUNK_SIZE:
        logger.warning("Warning: data length for today's stats is greater than 8 bytes")
    return parse_stats_chunk(data, today_variant=True)


def parse_daily_stats(
    data: bytes,
    address: int,
) -> list[tuple[datetime.datetime, ConsumptionStats]]:
    """Decode a run of daily chunks, starting at EEPROM *address*."""
    return [
        (
            date_from_address(address + index * STAT_CHUNK_SIZE),
            parse_stats_chunk(chunk),
        )
        for index, chunk in enumerate(chunk_bytes(data, STAT_CHUNK_SIZE))
    ]