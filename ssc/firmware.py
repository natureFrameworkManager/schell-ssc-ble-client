"""Decoding of the device info firmware packet (array index 0x01).

Payload layout (array index stripped)::

    0..1   : hardware version
    2..3   : bootloader version
    11..14 : reset reason flags
"""

from __future__ import annotations

from ssc.codecs import map_version
from ssc.types import FirmwareInfo

RESET_REASON_FLAGS: tuple[tuple[int, str], ...] = (
    (0x1, "PIN"),
    (0x2, "DOG"),
    (0x4, "SREQ"),
    (0x8, "LOCKUP"),
    (0x10000, "OFF"),
    (0x20000, "LPCOMP"),
    (0x40000, "DIF"),
    (0x80000, "NFC"),
)


def parse_reset_reason(reason: int) -> str:
    """Turn the reset reason bit field into a ``-`` separated flag list."""
    return "-".join(name for mask, name in RESET_REASON_FLAGS if reason & mask)


def parse_firmware_raw(data: bytes) -> FirmwareInfo:
    """Extract the raw version and reset reason fields."""
    if len(data) < 15:
        raise ValueError(
            f"Firmware payload must be at least 15 bytes, got {len(data)}"
        )
    return {
        "hardware_version_raw": data[0:2],
        "bootloader_version_raw": data[2:4],
        "reset_reason_raw": data[11:15],
    }


def parse_firmware(data: bytes) -> FirmwareInfo:
    """Decode firmware versions and the reset reason."""
    firmware = parse_firmware_raw(data)
    firmware.update(
        map_version(
            firmware["hardware_version_raw"],
            firmware["bootloader_version_raw"],
        )
    )
    firmware["reset_reason"] = parse_reset_reason(
        int.from_bytes(firmware["reset_reason_raw"], byteorder="little")
    )
    return firmware