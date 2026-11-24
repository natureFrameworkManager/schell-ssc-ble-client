"""Scanning for SSC devices."""

from __future__ import annotations

from collections.abc import Callable

import simplepyble

from ssc.constants import SSC_IDENTIFIER_PREFIX

StatusCallback = Callable[[], None]
FoundCallback = Callable[[simplepyble.Peripheral], None]


def _noop() -> None:
    """Default no-op callback."""


def is_ssc_device(peripheral: simplepyble.Peripheral) -> bool:
    """Whether *peripheral* is an SSC device (its name starts with ``SE2``)."""
    return SSC_IDENTIFIER_PREFIX in peripheral.identifier()


def ssc_devices(devices: list[simplepyble.Peripheral]) -> list[simplepyble.Peripheral]:
    """Only the SSC devices of a scan result."""
    return [device for device in devices if is_ssc_device(device)]


def unknown_devices(devices: list[simplepyble.Peripheral]) -> list[simplepyble.Peripheral]:
    """All non-SSC devices of a scan result."""
    return [device for device in devices if not is_ssc_device(device)]


def scan(
    adapter: simplepyble.Adapter,
    duration_s: int,
    on_start: StatusCallback | None = None,
    on_stop: StatusCallback | None = None,
    on_found: FoundCallback | None = None,
) -> list[simplepyble.Peripheral]:
    """Run a blocking scan and return the discovered peripherals."""
    adapter.set_callback_on_scan_start(on_start or _noop)
    adapter.set_callback_on_scan_stop(on_stop or _noop)
    adapter.set_callback_on_scan_found(on_found or (lambda peripheral: None))
    adapter.scan_for(duration_s * 1000)
    return adapter.scan_get_results()