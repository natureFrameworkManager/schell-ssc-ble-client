"""BLE session: connect the notification handlers and drive the request pump."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

import simplepyble

from ssc.ble.adapters import endpoint_label
from ssc.ble.tracker import RequestTracker
from ssc.config import Options
from ssc.constants import (
    ALL_CHARACTERISTICS,
    COMMAND_POLL_INTERVAL_S,
    DEVICE_INFO_CHARACTERISTIC,
    NOTIFICATION_SETTLE_S,
    SERVICE_UUID,
    SSC_CHARACTERISTIC,
)
from ssc.notifications import parse_response

StatusCallback = Callable[[str], None]
NotificationCallback = Callable[[bytes, object | None], None]


def _ignore_status(message: str) -> None:
    """Drop status messages when no callback was supplied."""


def _ignore_notification(data: bytes, parsed: object | None) -> None:
    """Drop notifications when no callback was supplied."""


class Session:
    """One connected SSC device.

    The session owns the :class:`~ssc.ble.tracker.RequestTracker`, parses every
    notification it receives and forwards raw+decoded data to the callbacks so
    that presentation stays in the CLI layer.
    """

    def __init__(
        self,
        device: simplepyble.Peripheral,
        options: Options | None = None,
        on_status: StatusCallback | None = None,
        on_info: NotificationCallback | None = None,
        on_ssc: NotificationCallback | None = None,
    ) -> None:
        self.device = device
        self.options = options or Options()
        self._status = on_status or _ignore_status
        self._on_info = on_info or _ignore_notification
        self._on_ssc = on_ssc or _ignore_notification
        self.tracker = RequestTracker(ALL_CHARACTERISTICS)

    # -- public API ---------------------------------------------------------

    def query(self, commands: Sequence[bytes]) -> None:
        """Send *commands* one at a time on the SSC characteristic."""
        self._status(f"Querying device: {endpoint_label(self.device)}")
        if not self.device.is_connected():
            self._status("    Device is not connected")
            return

        # Kept for output parity with the old client, which printed both lines.
        self._status("    Device is connected")
        self._status("    Device is now connected")

        self.device.notify(
            SERVICE_UUID,
            DEVICE_INFO_CHARACTERISTIC,
            self._handle_info_notification,
        )
        self.device.notify(
            SERVICE_UUID,
            SSC_CHARACTERISTIC,
            self._handle_ssc_notification,
        )
        self._status("Notification handler set up")

        self.tracker.enqueue(SSC_CHARACTERISTIC, commands)
        while self.tracker.waiting(SSC_CHARACTERISTIC) > 0:
            request = self.tracker.take_next(SSC_CHARACTERISTIC)
            if request is None:
                time.sleep(COMMAND_POLL_INTERVAL_S)
            else:
                self.device.write_command(SERVICE_UUID, SSC_CHARACTERISTIC, request)
        time.sleep(NOTIFICATION_SETTLE_S)  # let the last notification arrive

    # -- notification handlers ---------------------------------------------

    def _handle_info_notification(self, data: bytes) -> None:
        request = self.tracker.take_response_request(DEVICE_INFO_CHARACTERISTIC)
        parsed = parse_response(DEVICE_INFO_CHARACTERISTIC, data, request, self.options)
        self._on_info(data, parsed)

    def _handle_ssc_notification(self, data: bytes) -> None:
        request = self.tracker.take_response_request(SSC_CHARACTERISTIC)
        parsed = parse_response(SSC_CHARACTERISTIC, data, request, self.options)
        self._on_ssc(data, parsed)