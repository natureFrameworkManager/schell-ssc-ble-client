"""Interactive prompts: the only place that reads stdin."""

from __future__ import annotations

import simplepyble

from ssc.ble.adapters import endpoint_label
from ssc.constants import TEST_ADAPTER_IDENTIFIER

DEFAULT_CHOICE_PROMPT = "Enter choice: "


def ask_choice(prompt: str = DEFAULT_CHOICE_PROMPT) -> str:
    """Read one line of user input."""
    return input(prompt)


def ask_adapter(adapters: list[simplepyble.Adapter]) -> simplepyble.Adapter | None:
    """Let the user pick one of several adapters; ``None`` on invalid input."""
    print("Multiple adapters found")
    for index, adapter in enumerate(adapters):
        if adapter.identifier() == TEST_ADAPTER_IDENTIFIER:
            continue
        print(f"{index}: {endpoint_label(adapter)}")
    try:
        choice = int(ask_choice())
        return adapters[choice]
    except (ValueError, IndexError):
        return None


def ask_devices(devices: list[simplepyble.Peripheral]) -> list[simplepyble.Peripheral]:
    """Let the user pick one or more devices by comma separated indices."""
    print("Select a SSC device(s) to connect to [split by comma]:")
    for index, device in enumerate(devices):
        print(f"{index}: {endpoint_label(device)}")
    choice = ask_choice()
    return [devices[int(index)] for index in choice.split(",")]


def ask_service_characteristic(
    device: simplepyble.Peripheral,
) -> tuple[str, str]:
    """Interactive debugging helper: list and select a service/characteristic pair."""
    print("Successfully connected, listing services...")
    pairs: list[tuple[str, str]] = []
    for service in device.services():
        print(f"    Service UUID: {service.uuid()}")
        for characteristic in service.characteristics():
            print(f"      Characteristic UUID: {characteristic.uuid()}")
            print(f"        Characteristic capabilities: {characteristic.capabilities()}")
            print(f"        Characteristic writable command: {characteristic.can_write_command()}")
            print(f"        Characteristic writable request: {characteristic.can_write_request()}")
            pairs.append((service.uuid(), characteristic.uuid()))

    print("Please select a service/characteristic pair:")
    for index, (service_uuid, characteristic_uuid) in enumerate(pairs):
        print(f"{index}: {service_uuid} {characteristic_uuid}")

    return pairs[int(ask_choice())]