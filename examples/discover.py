"""Standalone scan lister, kept for manual debugging.

The real client (``python client.py``) uses the same helpers from
:mod:`ssc.ble.adapters` and :mod:`ssc.ble.scanner`.
"""

from __future__ import annotations

from ssc.ble.adapters import endpoint_label, get_adapters
from ssc.ble.scanner import scan


def main() -> int:
    adapters = get_adapters()
    if not adapters:
        print("No adapters found")
        return 1

    print("Please select an adapter:")
    for index, adapter in enumerate(adapters):
        print(f"{index}: {endpoint_label(adapter)}")

    adapter = adapters[int(input("Enter choice: "))]
    print(f"Selected adapter: {endpoint_label(adapter)}")

    peripherals = scan(
        adapter,
        5,
        on_start=lambda: print("Scan started."),
        on_stop=lambda: print("Scan complete."),
        on_found=lambda peripheral: print(f"Found {endpoint_label(peripheral)}"),
    )

    print("The following peripherals were found:")
    for peripheral in peripherals:
        connectable = "Connectable" if peripheral.is_connectable() else "Non-Connectable"
        print(f"{endpoint_label(peripheral)} - {connectable}")
        print(f"    Address Type: {peripheral.address_type()}")
        print(f"    Tx Power: {peripheral.tx_power()} dBm")

        for manufacturer_id, value in peripheral.manufacturer_data().items():
            print(f"    Manufacturer ID: {manufacturer_id}")
            print(f"    Manufacturer data: {value}")

        for service in peripheral.services():
            print(f"    Service UUID: {service.uuid()}")
            print(f"    Service data: {service.data()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())