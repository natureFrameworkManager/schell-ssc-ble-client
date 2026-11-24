"""Building the state query plan and decoding advertisements."""

from __future__ import annotations

import logging
from typing import Any

import simplepyble

from ssc.advertisement import (
    NAME_TYPE_ARTICLE_NUMBER,
    NAME_TYPE_SERIAL,
    parse_advertisement,
)
from ssc.constants import SSC_CHARACTERISTIC
from ssc.protocol.frames import (
    build_eeprom_dump_plan,
    build_module_info_request,
    build_read_array_request,
)
from ssc.recorder.config import RecorderConfig

logger = logging.getLogger(__name__)

#: Array reads that the existing parsers understand.
ARRAY_TELEMETRY = 0x00
ARRAY_FIRMWARE = 0x01
ARRAY_LIFETIME = 0x06
ARRAY_TODAY = 0x0B

ARRAY_LENGTHS = {
    ARRAY_TELEMETRY: 17,
    ARRAY_FIRMWARE: 15,
    ARRAY_LIFETIME: 8,
    ARRAY_TODAY: 8,
}


def build_state_query_plan(config: RecorderConfig) -> list[tuple[str, bytes]]:
    """Return the commands that capture the complete device state."""
    plan: list[tuple[str, bytes]] = [
        (SSC_CHARACTERISTIC, request)
        for request in build_eeprom_dump_plan(
            config.eeprom_start, config.eeprom_end + 1
        )
    ]
    plan.extend(
        (
            SSC_CHARACTERISTIC,
            build_read_array_request(index, length),
        )
        for index, length in ARRAY_LENGTHS.items()
    )
    plan.append((SSC_CHARACTERISTIC, build_module_info_request()))
    return plan


def read_advertisement(
    peripheral: simplepyble.Peripheral,
) -> dict[str, Any] | None:
    """Decode the first manufacturer-data blob of a peripheral."""
    try:
        manufacturer_data = peripheral.manufacturer_data()
    except Exception:  # noqa: BLE001 - an incomplete scan result is not fatal
        logger.debug("Could not read manufacturer data", exc_info=True)
        return None
    for value in manufacturer_data.values():
        if len(value) < 19:
            continue
        try:
            return dict(parse_advertisement(value))
        except Exception:  # noqa: BLE001
            logger.debug("Could not decode advertisement", exc_info=True)
    return None


def safe_rssi(peripheral: simplepyble.Peripheral) -> int | None:
    try:
        return int(peripheral.rssi())
    except Exception:  # noqa: BLE001
        return None


def advertisement_identity(
    advertisement: dict[str, Any] | None,
) -> tuple[str | None, str | None, str | None]:
    """Return ``(serial, display_name, product)`` from an advertisement."""
    if advertisement is None:
        return None, None, None

    raw_name = advertisement.get("serial_display_name")
    display_name = advertisement.get("device_name")
    serial: str | None = None
    if isinstance(raw_name, bytes) and raw_name:
        if raw_name[0] == NAME_TYPE_SERIAL and len(raw_name) >= 9:
            serial = raw_name[3:9].hex().upper()
        elif raw_name[0] == NAME_TYPE_ARTICLE_NUMBER:
            serial = None

    type_name = advertisement.get("device_type_name") or ""
    subtype_name = advertisement.get("device_subtype_name") or ""
    product = " ".join(part for part in (type_name, subtype_name) if part).strip()
    return serial, display_name, product or None