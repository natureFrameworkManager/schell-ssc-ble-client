"""Builders for the binary request frames sent to the device.

Frame layout::

    byte 0    : length (number of bytes that follow + 1)
    byte 1    : opcode (one of the ``CMD_*`` constants)
    byte 2..N : payload, layout depends on the opcode
"""

from __future__ import annotations

import logging

from ssc.constants import (
    ARRAY_CHUNK_SIZE,
    CMD_DIG_WRITE_BIT,
    CMD_READ_ARRAY,
    CMD_READ_EE_BY_ADDR,
    CMD_WRITE_EE_BY_ADDR,
    EEPROM_ADDRESS_SPACE_END,
    EEPROM_CHUNK_SIZE,
)

logger = logging.getLogger(__name__)


def build_request(command: int, payload: bytes) -> bytes:
    """Wrap *payload* in a length/opcode frame."""
    request = bytearray()
    request.append(1 + 1 + len(payload))  # length byte + command byte + payload
    request.append(command)
    request.extend(payload)
    logger.debug("Built request: %s", request.hex(" "))
    return bytes(request)


def build_read_request(address: int, length: int) -> bytes:
    """Read *length* bytes from EEPROM *address* (16 bit, high byte first)."""
    if address >= EEPROM_ADDRESS_SPACE_END:
        logger.warning(
            "Warning: Actual address space only goes up to 0x4000. Afterwards it is wrapped around"
        )
    if address < 0 or address > 0xFFFF:
        raise ValueError("Address must be between 0 and 65535")
    if length == 0:
        raise ValueError("Length cannot be zero")
    if length > 0xFF:
        raise ValueError("Length cannot exceed 255 bytes")
    payload = bytearray()
    payload.append(address >> 8)
    payload.append(address & 0xFF)
    payload.append(length)
    logger.debug("Read request payload: %s", payload.hex(" "))
    return build_request(CMD_READ_EE_BY_ADDR, bytes(payload))


def build_write_request(address: int, data: bytes) -> bytes:
    """Write *data* to EEPROM *address*."""
    if len(data) == 0:
        raise ValueError("Data to write cannot be empty")
    if len(data) > 0xFF:
        raise ValueError("Data to write cannot exceed 255 bytes")
    if address < 0 or address > 0xFFFF:
        raise ValueError("Address must be between 0 and 65535")
    payload = bytearray()
    payload.append(address >> 8)
    payload.append(address & 0xFF)
    payload.append(len(data))
    payload.extend(data)
    logger.debug("Write request payload: %s", payload.hex(" "))
    return build_request(CMD_WRITE_EE_BY_ADDR, bytes(payload))


def build_write_bit_request(bit_address: int, value: int) -> bytes:
    """Set a single control bit.

    Address 1: valve state (open/close), 2: LED red, 4: LED orange,
    5: thermal desinfection, 6: stagnation flush, 7: continuous flush
    ("Dauerlauf"), 8: cleaning stop, 9: TD special.
    """
    if bit_address < 0 or bit_address > 0xFF:
        raise ValueError("Bit address must be between 0 and 255")
    if value not in (0, 1):
        raise ValueError("Value must be 0 or 1")
    payload = bytes((bit_address, value))
    logger.debug("Write bit request payload: %s", payload.hex(" "))
    return build_request(CMD_DIG_WRITE_BIT, payload)


def build_read_array_request(index: int, length: int) -> bytes:
    """Read *length* bytes starting at array *index*."""
    if length == 0:
        raise ValueError("Length cannot be zero")
    if length > 0xFF:
        raise ValueError("Length cannot exceed 255 bytes")
    if index < 0 or index > 0xFF:
        raise ValueError("Index must be between 0 and 255")
    payload = bytes((index, length))
    logger.debug("Read array request payload: %s", payload.hex(" "))
    return build_request(CMD_READ_ARRAY, payload)


def build_eeprom_dump_plan(
    start: int = 0x0000,
    end: int = 0xFFFF,
    overlap: int = 0,
) -> list[bytes]:
    """Return the read requests needed to dump EEPROM ``start..end``."""
    step = EEPROM_CHUNK_SIZE - overlap
    return [
        build_read_request(address, EEPROM_CHUNK_SIZE)
        for address in range(start, end, step)
    ]


def build_array_dump_plan(
    start: int = 0x00,
    end: int = 0xFF,
    overlap: int = 0,
) -> list[bytes]:
    """Return the read requests needed to dump array ``start..end``."""
    step = ARRAY_CHUNK_SIZE - overlap
    return [
        build_read_array_request(index, ARRAY_CHUNK_SIZE)
        for index in range(start, end, step)
    ]