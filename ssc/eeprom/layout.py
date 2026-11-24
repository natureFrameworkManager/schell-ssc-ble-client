"""Declarative description of the known EEPROM fields.

``FIELDS`` maps every known contiguous EEPROM range to a name and a parser;
``MARKERS`` documents the ranges that carry no value of their own (block
boundaries).  Extraction only ever iterates ``FIELDS``, so markers can be
added for documentation without changing the extracted result.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass

from ssc.codecs import bcd_to_int
from ssc.eeprom.calendar import parse_calendar


@dataclass(frozen=True, slots=True)
class EepromField:
    """One named, contiguous EEPROM range and how to decode it."""

    name: str
    address: int
    length: int
    loads: Callable[[bytes], object]


@dataclass(frozen=True, slots=True)
class EepromMarker:
    """A boundary or reserved range without a decoded value."""

    name: str
    address: int


def _little_endian(data: bytes) -> int:
    return int.from_bytes(data, "little")


def _byte(data: bytes) -> int:
    return int.from_bytes(data)


def _flag(data: bytes) -> bool:
    return bool(data[0])


def _flag_not_zero(data: bytes) -> bool:
    return bool(data[0] != 0)


def _cp1250_text(data: bytes) -> str:
    return data.decode("cp1250").rstrip("\x00")


def _ascii_text(data: bytes) -> str:
    return data.decode("ascii").rstrip("\x00")


def _article_number(data: bytes) -> str:
    return "{0:X}-{1:X}-{2:X}-{3:X}-{4:X}".format(
        data[4], data[3], data[2], data[1], data[0]
    )


def _installation_date(data: bytes) -> datetime.date:
    """BCD year/month/day, e.g. 26 07 24 -> 2026-07-24."""
    return datetime.date(
        2000 + bcd_to_int(data[0]),
        bcd_to_int(data[1]),
        bcd_to_int(data[2]),
    )


def _sensor_range(data: bytes) -> str:
    return ["short", "mid", "long"][data[0]]


def _stagnation_flush_mode(data: bytes) -> bool:
    return bool(data[0] == 2)


def _need_based(data: bytes) -> bool:
    return bool(data[0] == 0x7F)


def _sensor_expert_mode(data: bytes) -> bool:
    # NOTE: kept from the original client; ``bool(data)`` is always True for a
    # non-empty byte string.
    return bool(data)


def _log_index(base: int) -> Callable[[bytes], int]:
    """Parser for a log ``nextIndex`` byte stored relative to *base*."""

    def load(data: bytes) -> int:
        return int.from_bytes(data) * 8 + base

    return load


FIELDS: tuple[EepromField, ...] = (
    EepromField("EEPROM_ArticleNumber", 32, 5, _article_number),
    EepromField("EEPROM_CleaningStop_enabled", 108, 1, _flag),
    EepromField("EEPROM_CleaningStop_runtime", 109, 2, _little_endian),
    EepromField("EEPROM_StagnationAndFollowUp", 112, 2, _little_endian),
    EepromField("EEPROM_FollowUpRuntime", 114, 2, _little_endian),
    EepromField("EEPROM_StagnationFlushInterval_mode", 118, 1, _stagnation_flush_mode),
    EepromField("EEPROM_StagnationFlushInterval_hours", 119, 2, _little_endian),
    EepromField("EEPROM_StagnationFlushInterval_runtime", 121, 2, _little_endian),
    EepromField("EEPROM_HybridMode", 128, 1, _flag),
    EepromField("EEPROM_HybridInterval", 129, 1, _byte),
    EepromField("EEPROM_HybridRuntime", 130, 1, _byte),
    EepromField("EEPROM_PreFlushMode", 146, 1, _flag),
    EepromField("EEPROM_PreFlushStart", 147, 1, _byte),
    EepromField("EEPROM_SensorRange", 148, 1, _sensor_range),
    EepromField("EEPROM_Scenario", 149, 1, _byte),
    EepromField("EEPROM_PreFlushRuntime", 158, 1, _byte),
    EepromField("EEPROM_StadionMode", 162, 1, _flag),
    EepromField("EEPROM_OdourStopMode", 163, 1, _flag),
    EepromField("EEPROM_OdourStopInterval", 164, 1, _byte),
    EepromField("EEPROM_StadionRuntime", 167, 1, _byte),
    EepromField("EEPROM_ContinuousEnabled", 168, 1, _flag),
    EepromField("EEPROM_ContinuousRuntime", 169, 2, _little_endian),
    EepromField("EEPROM_ThermalEnabled", 171, 1, _flag),
    EepromField("EEPROM_ThermalRuntime", 172, 2, _little_endian),
    EepromField("EEPROM_OdourStopRuntime", 174, 1, _byte),
    EepromField("EEPROM_Installer", 176, 15, _cp1250_text),
    EepromField("EEPROM_InstallationDate", 192, 3, _installation_date),
    EepromField("EEPROM_WcFlushDuration", 200, 1, _byte),  # TODO: lookup via WCTable
    EepromField("EEPROM_Location", 208, 15, _cp1250_text),
    EepromField("EEPROM_AmbiantSensorEnabled", 276, 1, _flag_not_zero),
    EepromField("EEPROM_LongRangeMode", 284, 2, _little_endian),
    EepromField("EEPROM_RaweId", 288, 10, _ascii_text),
    EepromField("EEPROM_LongRangeModeInterval", 347, 2, _little_endian),
    EepromField("EEPROM_UserDetectionModeInterval", 349, 2, _little_endian),
    EepromField("EEPROM_HandDetectTime", 362, 2, _little_endian),
    EepromField("EEPROM_SwitchOffInterval", 370, 2, _little_endian),
    EepromField("EEPROM_DeviceName", 512, 12, _cp1250_text),
    EepromField("EEPROM_DevicePassword", 528, 7, _cp1250_text),
    EepromField("EEPROM_Password", 535, 7, _cp1250_text),
    EepromField("EEPROM_StagnationFlushLog_nextIndex", 589, 1, _log_index(1024)),
    EepromField("EEPROM_ThermalDesinfectionLog_nextIndex", 590, 1, _log_index(2048)),
    EepromField("EEPROM_DauerlaufLog_nextIndex", 592, 1, _log_index(2176)),
    EepromField("EEPROM_CleaningStopLog_nextIndex", 593, 1, _log_index(2304)),
    EepromField("EEPROM_FlowRate", 594, 1, _byte),
    EepromField("EEPROM_SensorExpertMode", 606, 1, _sensor_expert_mode),
    EepromField("EEPROM_CalendarStart", 768, 112, parse_calendar),
    EepromField("EEPROM_NeedBased", 896, 8, _need_based),
)

MARKERS: tuple[EepromMarker, ...] = (
    EepromMarker("EEPROM_ThermalAndContinuous", 160),
    EepromMarker("EEPROM_ConfigStart", 256),
    EepromMarker("EEPROM_RangeMode", 336),
    EepromMarker("EEPROM_ConfigEnd", 383),
    EepromMarker("EEPROM_CalendarEnd", 880),
)