"""Decoding of the device info telemetry packet (array index 0x00).

Payload layout, all multi-byte fields little endian::

    0..3   : temperature (32 bit)
    4..5   : battery voltage (16 bit)
    6..7   : VCC (16 bit)
    8..9   : 3.3 V rail (16 bit)
    10..11 : year (16 bit)
    12     : month
    13     : day
    14     : hour
    15     : minute
    16     : second
"""

from __future__ import annotations

from ssc.codecs import calculate_battery, calculate_date_time, calculate_voltage
from ssc.types import Telemetry


def parse_telemetry_raw(data: bytes) -> Telemetry:
    """Extract the raw telemetry fields."""
    return {
        "temperature": int.from_bytes(data[0:4], byteorder="little"),
        "battery_voltage_raw": int.from_bytes(data[4:6], byteorder="little"),
        "vcc_raw": int.from_bytes(data[6:8], byteorder="little"),
        "3.3v": int.from_bytes(data[8:10], byteorder="little"),
        "year": int.from_bytes(data[10:12], byteorder="little"),
        "month": data[12],
        "day": data[13],
        "hour": data[14],
        "minute": data[15],
        "second": data[16],
    }


def parse_telemetry(data: bytes) -> Telemetry:
    """Decode telemetry and add the derived voltage/battery/date values."""
    telemetry = parse_telemetry_raw(data)
    battery = calculate_battery(telemetry["battery_voltage_raw"])
    telemetry["battery"] = battery
    telemetry["vcc"] = calculate_voltage(telemetry["vcc_raw"])
    telemetry["datetime"] = calculate_date_time(
        telemetry["year"],
        telemetry["month"],
        telemetry["day"],
        telemetry["hour"],
        telemetry["minute"],
        telemetry["second"],
    )
    return telemetry