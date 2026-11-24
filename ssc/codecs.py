"""Value conversions shared by the decoding modules."""

from __future__ import annotations

import datetime


def chunk_bytes(data: bytes, size: int) -> list[bytes]:
    """Split *data* into chunks of at most *size* bytes."""
    return [data[i:i + size] for i in range(0, len(data), size)]


def bcd_to_int(value: int) -> int:
    """Convert one packed BCD byte (e.g. 0x24) into its decimal value (24)."""
    return ((value >> 4) & 0x0F) * 10 + (value & 0x0F)


def parse_version(data: bytes) -> str:
    """Decode a two byte version field, e.g. ``V01.23`` or ``T01.23``."""
    if data[0] & 0b10000000:
        return f"T{data[0] & 0x7F:02d}.{data[1]:02d}"
    return f"V{data[0]:02d}.{data[1]:02d}"


def map_version(hardware_version: bytes, bootloader_version: bytes) -> dict[str, str]:
    """Decode the two raw version fields of the firmware info response."""
    return {
        "hardware_version": parse_version(hardware_version),
        "bootloader_version": parse_version(bootloader_version),
    }


def calculate_battery(battery_voltage_adv: int) -> dict[str, float | int]:
    """Turn a battery value in 0.1 V steps into volts and a percentage.

    Values below 4.5 V count as empty, 6 V and above as full; everything in
    between is interpolated linearly.
    """
    battery_voltage = battery_voltage_adv / 10
    if battery_voltage <= 4.5:
        battery_level = 0
    elif battery_voltage > 6:
        battery_level = 100
    else:
        battery_level = int((battery_voltage - 4.5) / (6 - 4.5) * 100)
    return {"battery_voltage": battery_voltage, "battery_level": battery_level}


def calculate_voltage(millivolts: int) -> float:
    """Millivolts to volts."""
    return millivolts / 1000.0


def calculate_date_time(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
) -> datetime.datetime:
    """Build a datetime from the individual fields of the telemetry packet."""
    return datetime.datetime(year, month, day, hour, minute, second)