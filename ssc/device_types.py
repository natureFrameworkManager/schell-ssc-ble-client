"""Lookup tables that turn advertisement type codes into product names."""

from __future__ import annotations

from ssc.types import DeviceTypeNames

DEVICE_TYPE_NAMES: dict[int, str] = {
    0x00: "Unrecognized",
    0x02: "Waschtisch",
    0x03: "Urinal",
    0x04: "WC",
    0x10: "CVD/Solenoid",
    0xF0: "BLE-Basic",
    0xF1: "BLE-Vitus",
    0xF2: "BLE-Montus-Flow",
}

WASCHTISCH_SUBTYPE_NAMES: dict[int, str] = {
    1: "Celis E²",
    10: "Puris E²",
    11: "Venus E²",
    12: "Xeris E²",
    20: "Vitus IR",
    21: "Grandis E",
    30: "Linus E",
    31: "Walis E",
}

URINAL_SUBTYPE_NAMES: dict[int, str] = {
    1: "Schelltronic",
    2: "Urinal",
}

# High nibble of the sub-sub type: size class.
SUBTYPE_HIGH_NAMES: dict[int, str] = {
    0: "",
    1: "S",
    2: "M",
    3: "L",
}

# Low nibble of the sub-sub type: nozzle/variant.
SUBTYPE_LOW_NAMES: dict[int, str] = {
    0: "",
    1: "HD-K",
    2: "HD-M",
    3: "ND-M",
    4: "HD-T",
    5: "HD-SP",
    6: "HD-SP",
}

UNKNOWN_SUBTYPE_NAME = "Unbekannte Armatur"


def map_device_types(
    device_type: int | None,
    device_sub_type: int | None,
    device_sub_sub_type: int | None,
) -> DeviceTypeNames:
    """Resolve the type codes of an advertisement into human readable names."""
    device_type_code = device_type if device_type is not None else 0x00
    sub_type_code = device_sub_type if device_sub_type is not None else 0x00
    sub_sub_type_code = device_sub_sub_type if device_sub_sub_type is not None else 0x00

    device_type_name = DEVICE_TYPE_NAMES.get(device_type_code, "Unknown")

    if device_type_name == "Waschtisch":
        sub_type_name = WASCHTISCH_SUBTYPE_NAMES.get(sub_type_code, UNKNOWN_SUBTYPE_NAME)
    elif device_type_name == "Urinal":
        sub_type_name = URINAL_SUBTYPE_NAMES.get(sub_type_code, UNKNOWN_SUBTYPE_NAME)
    else:
        sub_type_name = ""

    high_name = SUBTYPE_HIGH_NAMES.get(sub_sub_type_code >> 4, "")
    # NOTE: the low nibble is intentionally *not* masked here.  The original
    # client looked up the whole byte for this field; masking with 0x0F would
    # change decoded output for sub-sub types >= 0x10.
    low_name = SUBTYPE_LOW_NAMES.get(sub_sub_type_code, "")

    return {
        "device_type_name": device_type_name,
        "device_subtype_name": sub_type_name,
        "device_subsubtype_high_name": high_name,
        "device_subsubtype_low_name": low_name,
    }