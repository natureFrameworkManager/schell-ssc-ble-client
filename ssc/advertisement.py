"""Decoding of the SSC manufacturer data blob sent in advertisements.

Layout (indices into the manufacturer data value)::

    byte 0     : device type
    byte 1     : device sub type
    byte 2..13 : serial / display name
    byte 16    : device sub-sub type
    byte 18    : battery voltage (0.1 V steps)
"""

from __future__ import annotations

import logging

from ssc.codecs import calculate_battery
from ssc.device_types import map_device_types
from ssc.types import Advertisement, RawAdvertisement

logger = logging.getLogger(__name__)

NAME_TYPE_ARTICLE_NUMBER = 0x0D
NAME_TYPE_SERIAL = 0x0A


def parse_advertisement_raw(data: bytes) -> RawAdvertisement:
    """Extract the raw fields of an advertisement."""
    return {
        "device_type": data[0],
        "device_sub_type": data[1],
        "serial_display_name": data[2:14],
        "device_sub_sub_type": data[16],
        "battery_voltage_adv": data[18],
    }


def calculate_device_name(serial_display_name: bytes | None) -> str:
    """Decode the name field of an advertisement.

    * ``[0] == 0x0D``: bytes 1..5 hold a packed article number.
    * ``[0] == 0x0A``: bytes 3..8 hold a 6 byte hex serial number.
    * otherwise: 12 bytes of CP1250 free text, null trimmed.
    """
    if not serial_display_name:
        return ""
    data = serial_display_name
    if data[0] == NAME_TYPE_ARTICLE_NUMBER:
        # NOTE: the original used "{0:X1}" / "{1:X2}", which is not a valid
        # Python format spec and raised ValueError for every article number.
        return "{0:X}-{1:02X}-{2:02X}-{3:02X}-{4:02X}".format(
            data[1], data[2], data[3], data[4], data[5]
        )
    if data[0] == NAME_TYPE_SERIAL:
        return "".join("{:02X}".format(byte) for byte in data[3:9])
    return data.decode("cp1250").rstrip("\x00")


def parse_advertisement(data: bytes) -> Advertisement:
    """Decode an advertisement into raw fields, type names and battery state."""
    logger.debug("Raw advertisement data: %s", data.hex(" "))
    advertisement: Advertisement = parse_advertisement_raw(data)
    advertisement.update(
        map_device_types(
            advertisement["device_type"],
            advertisement["device_sub_type"],
            advertisement["device_sub_sub_type"],
        )
    )
    advertisement["device_name"] = calculate_device_name(advertisement["serial_display_name"])
    advertisement.update(calculate_battery(advertisement["battery_voltage_adv"]))
    return advertisement