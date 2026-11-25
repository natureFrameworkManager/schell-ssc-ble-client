"""Typed shapes of the decoded payloads.

These are documentation/typing aids only: the parsers return plain dicts.
"""

from __future__ import annotations

import datetime
from typing import TypedDict


class BatteryInfo(TypedDict):
    battery_voltage: float
    battery_level: int


class RawAdvertisement(TypedDict):
    """Raw fields of the SSC manufacturer data blob."""

    device_type: int
    device_sub_type: int
    serial_display_name: bytes
    device_sub_sub_type: int
    battery_voltage_adv: int


class DeviceTypeNames(TypedDict):
    device_type_name: str
    device_subtype_name: str
    device_subsubtype_high_name: str
    device_subsubtype_low_name: str


class Advertisement(RawAdvertisement, DeviceTypeNames):
    """Fully decoded advertisement."""

    device_name: str
    battery_voltage: float
    battery_level: int


class Telemetry(TypedDict, total=False):
    """Decoded telemetry packet.

    Note: the raw 3.3 V rail reading is exposed under the literal key
    ``"3.3v"`` for backwards compatibility.
    """

    temperature: int
    battery_voltage_raw: int
    vcc_raw: int
    vcc: float
    battery: BatteryInfo
    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    datetime: datetime.datetime | None


class FirmwareInfo(TypedDict, total=False):
    hardware_version_raw: bytes
    bootloader_version_raw: bytes
    reset_reason_raw: bytes
    hardware_version: str
    bootloader_version: str
    reset_reason: str


class CalendarChunk(TypedDict):
    bitmask: int
    hour: int
    minute: int
    second: int
    runtime: int
    reserved: bytes


class CalendarEntry(CalendarChunk):
    bitmask_mapped: tuple[str, str | None]


ConsumptionStats = TypedDict(
    "ConsumptionStats",
    {
        "count-normal": int,
        "runtime-normal": int,
        "count-stagnation": int,
        "runtime-stagnation": int,
        "aerator-liters-per-minute": int,
        "consumption-normal-liters": float,
        "consumption-stagnation-liters": float,
    },
    total=False,
)

LifetimeStats = TypedDict(
    "LifetimeStats",
    {
        "count-restart": int,
        "count-lifetime": int,
    },
)