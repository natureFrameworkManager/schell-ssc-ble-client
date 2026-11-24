"""Decoding of notifications received on the three SSC characteristics.

Packet layout (identical for all characteristics)::

    byte 0    : length (total number of bytes in the packet)
    byte 1    : opcode / command
    byte 2..N : payload (depends on the command)

Some responses only echo an index or address instead of the data itself, so
decoding needs the request that triggered the response.  :class:`ssc.ble.
tracker.RequestTracker` hands the in-flight request to :func:`parse_response`
and marks it as answered at the same time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from ssc.bits import parse_bit_read
from ssc.codecs import parse_version
from ssc.config import Options
from ssc.constants import (
    CMD_DIG_READ_BYTE,
    CMD_DIG_WRITE_BIT,
    CMD_READ_ARRAY,
    CMD_READ_EE_BY_ADDR,
    CMD_READ_MODULE_INFO,
    CMD_WRITE_EE_BY_ADDR,
    DEVICE_CONFIG_CHARACTERISTIC,
    DEVICE_INFO_CHARACTERISTIC,
    SSC_CHARACTERISTIC,
)
from ssc.eeprom.daily_stats import parse_daily_stats, parse_today_stats
from ssc.eeprom.event_history import parse_event_history
from ssc.eeprom.extract import extract_eeprom
from ssc.eeprom.regions import EepromRegion, classify_address
from ssc.firmware import parse_firmware
from ssc.stats import parse_lifetime_stats
from ssc.telemetry import parse_telemetry

logger = logging.getLogger(__name__)

Handler = Callable[[int, bytes, bytes | None, Options], object | None]
SscHandler = Callable[[bytes, bytes, Options], object]

#: Responses on the config characteristic carry no payload, only the ack text.
DEVICE_CONFIG_RESPONSES: dict[int, str] = {
    CMD_READ_EE_BY_ADDR: "config read",
    CMD_WRITE_EE_BY_ADDR: "config write",
    CMD_DIG_WRITE_BIT: "config bit_write",
    CMD_READ_ARRAY: "config read_array",
}

#: Device info responses are addressed by the array index in the first payload byte.
DEVICE_INFO_RESPONSES: dict[int, Callable[[bytes], object]] = {
    0x00: parse_telemetry,
    0x01: parse_firmware,
}


def _log_unknown_command(command: int, payload: bytes) -> None:
    logger.warning("Unknown command: %s payload: %s", command, payload.hex(" "))


def _parse_device_info(
    command: int,
    payload: bytes,
    request: bytes | None,
    options: Options,
) -> object | None:
    if command == CMD_READ_ARRAY and payload:
        parser = DEVICE_INFO_RESPONSES.get(payload[0])
        if parser is not None:
            return parser(payload[1:])
    _log_unknown_command(command, payload)
    return None


def _parse_device_config(
    command: int,
    payload: bytes,
    request: bytes | None,
    options: Options,
) -> object | None:
    if request is None:
        logger.warning("Original request is None for config")
        return None
    response = DEVICE_CONFIG_RESPONSES.get(command)
    if response is None:
        _log_unknown_command(command, payload)
    return response


def _ssc_read_module_info(payload: bytes, request: bytes, options: Options) -> dict[str, object]:
    """Request: ``[8..9]`` app version, ``[10..15]`` serial."""
    return {
        "app_version": parse_version(request[8:10]),
        "serial": request[10:16],
    }


def _ssc_read_eeprom(payload: bytes, request: bytes, options: Options) -> object:
    """Request: ``[2]`` address high, ``[3]`` address low, ``[4]`` length."""
    address = (request[2] << 8) | request[3]
    region = classify_address(address)
    if region is EepromRegion.CONFIG:
        return extract_eeprom(payload, address, options)
    if region is EepromRegion.DAILY_STATS:
        return parse_daily_stats(payload, address)
    if region is EepromRegion.EVENT_HISTORY:
        return parse_event_history(payload, address)
    return "unknown eeprom address: " + hex(address)


def _ssc_dig_read_byte(payload: bytes, request: bytes, options: Options) -> object:
    """Request: ``[2]`` address bit."""
    return parse_bit_read(payload[0], payload[1])


def _ssc_write_eeprom(payload: bytes, request: bytes, options: Options) -> object:
    """Request: ``[2..3]`` address, ``[4]`` length, ``[5..]`` data."""
    return "write"


def _ssc_write_bit(payload: bytes, request: bytes, options: Options) -> object:
    """Request: ``[2]`` address bit, ``[3]`` value."""
    return "bit_write"


def _ssc_read_array(payload: bytes, request: bytes, options: Options) -> object:
    """Request: ``[2]`` array index, ``[3]`` length."""
    index = request[2]
    if index == 0x06:
        return parse_lifetime_stats(payload[1:])
    if index == 0x0B:
        return parse_today_stats(payload[1:])
    return f"unknown ssc command: {CMD_READ_ARRAY}"


#: SSC opcodes and their handlers (payload, original request) -> decoded result.
SSC_HANDLERS: dict[int, SscHandler] = {
    CMD_READ_MODULE_INFO: _ssc_read_module_info,
    CMD_READ_EE_BY_ADDR: _ssc_read_eeprom,
    CMD_DIG_READ_BYTE: _ssc_dig_read_byte,
    CMD_WRITE_EE_BY_ADDR: _ssc_write_eeprom,
    CMD_DIG_WRITE_BIT: _ssc_write_bit,
    CMD_READ_ARRAY: _ssc_read_array,
}


def _parse_ssc(
    command: int,
    payload: bytes,
    request: bytes | None,
    options: Options,
) -> object | None:
    if request is None:
        logger.warning("Original request is None for SSC")
        return None
    handler = SSC_HANDLERS.get(command)
    if handler is None:
        return f"unknown ssc command: {command}"
    return handler(payload, request, options)


#: Characteristic UUID -> handler taking (command, payload, request, options).
HANDLERS: dict[str, Handler] = {
    DEVICE_INFO_CHARACTERISTIC: _parse_device_info,
    DEVICE_CONFIG_CHARACTERISTIC: _parse_device_config,
    SSC_CHARACTERISTIC: _parse_ssc,
}


def parse_response(
    characteristic: str,
    data: bytes,
    request: bytes | None = None,
    options: Options | None = None,
) -> object | None:
    """Decode one notification packet from *characteristic*."""
    options = options or Options()
    logger.debug("Raw notify response data: %s", data.hex(" "))
    length = data[0]
    if length != len(data):
        raise ValueError("Invalid data length")
    command = data[1]
    payload = data[2:]
    handler = HANDLERS.get(characteristic)
    if handler is None:
        _log_unknown_command(command, payload)
        return None
    return handler(command, payload, request, options)