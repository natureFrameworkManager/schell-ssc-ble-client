"""User facing output: scanning, device listings and notification printers."""

from __future__ import annotations

from collections.abc import Callable

import simplepyble

from ssc.advertisement import parse_advertisement
from ssc.ble.adapters import endpoint_label
from ssc.ble.scanner import is_ssc_device
from ssc.config import Options

NotificationCallback = Callable[[bytes, object | None], None]


def scan_found(peripheral: simplepyble.Peripheral, options: Options) -> None:
    """Print a device discovered during the scan, honouring the verbosity flags."""
    ssc = is_ssc_device(peripheral)
    if ssc and not options.scan_debug_ssc:
        return
    if not ssc and not options.scan_show_unknown:
        return
    kind = "SSC" if ssc else "unknown"
    print(f"Discovered {kind} device: {endpoint_label(peripheral)}")


def print_peripheral_details(peripheral: simplepyble.Peripheral) -> None:
    """Print the generic properties, manufacturer data and services."""
    print(f"    Address Type: {peripheral.address_type()}")
    print(f"    Tx Power: {peripheral.tx_power()} dBm")

    for manufacturer_id, value in peripheral.manufacturer_data().items():
        print(f"    Manufacturer ID: {manufacturer_id}")
        print(f"    Manufacturer data: {value.hex(' ')}")

    for service in peripheral.services():
        print(f"    Service UUID: {service.uuid()}")
        print(f"    Service data: {service.data().hex(' ')}")


def display_ssc_device(peripheral: simplepyble.Peripheral, options: Options) -> None:
    """Print an SSC device including its decoded advertisements."""
    print(f"Found SSC device: {endpoint_label(peripheral)}")
    if options.scan_debug_ssc:
        print(f"    Connectable: {'Yes' if peripheral.is_connectable() else 'No'}")
        print_peripheral_details(peripheral)
    for value in peripheral.manufacturer_data().values():
        print(parse_advertisement(value))


def display_unknown_device(peripheral: simplepyble.Peripheral) -> None:
    """Print a non SSC device with its raw properties."""
    connectable = "Connectable" if peripheral.is_connectable() else "Non-Connectable"
    print(f"Found unknown device ({connectable}): {endpoint_label(peripheral)}")
    print_peripheral_details(peripheral)


def notification_handlers(
    options: Options,
) -> tuple[NotificationCallback, NotificationCallback]:
    """Build the ``on_info`` / ``on_ssc`` callbacks for a session."""

    def on_info(data: bytes, parsed: object | None) -> None:
        if data[2] == 0x00 and not options.show_telemetry:
            return
        print(f"Info Notification: {data.hex(' ')}")
        print(f"Parsed: {parsed}")

    def on_ssc(data: bytes, parsed: object | None) -> None:
        print(f"SSC Notification: {data.hex(' ')}")
        print(f"Parsed: {parsed}")

    return on_info, on_ssc