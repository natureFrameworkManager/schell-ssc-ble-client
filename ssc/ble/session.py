"""BLE session: connect the notification handlers and drive the request pump."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str], None]
NotificationCallback = Callable[[bytes, object | None], None]
RawNotificationCallback = Callable[
    [str, bytes | None, bytes, object | None], None
]


def _ignore_status(message: str) -> None:
    """Drop status messages when no callback was supplied."""


def _ignore_notification(data: bytes, parsed: object | None) -> None:
    """Drop notifications when no callback was supplied."""


def _ignore_raw(
    characteristic: str,
    request: bytes | None,
    data: bytes,
    parsed: object | None,
) -> None:
    """Drop raw notifications when no callback was supplied."""


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
        on_raw: RawNotificationCallback | None = None,
    ) -> None:
        self.device = device
        self.options = options or Options()
        self._status = on_status or _ignore_status
        self._on_info = on_info or _ignore_notification
        self._on_ssc = on_ssc or _ignore_notification
        self._on_raw = on_raw or _ignore_raw
        self.tracker = RequestTracker(ALL_CHARACTERISTICS)

    # -- public API ---------------------------------------------------------

    def query(self, commands: Sequence[bytes]) -> None:
        """Send *commands* one at a time on the SSC characteristic."""
        self.query_plan(
            [(SSC_CHARACTERISTIC, command) for command in commands],
            timeout_s=300.0,
            request_timeout_s=5.0,
        )

    def query_plan(
        self,
        plan: Sequence[tuple[str, bytes]],
        *,
        timeout_s: float | None = None,
        request_timeout_s: float | None = None,
        settle_s: float | None = None,
    ) -> None:
        """Send commands grouped by characteristic.

        A full EEPROM dump takes a long time, so an overall timeout and a
        per-request timeout are supported.  A request that is never answered is
        dropped and the pump continues; missing data is visible in the
        collector's coverage.
        """
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

        for characteristic in ALL_CHARACTERISTICS:
            requests = [
                request for target, request in plan if target == characteristic
            ]
            if requests:
                self.tracker.enqueue(characteristic, requests)

        deadline = time.monotonic() + timeout_s if timeout_s else None
        while not all(
            self.tracker.is_idle(characteristic)
            for characteristic in ALL_CHARACTERISTICS
        ):
            if deadline is not None and time.monotonic() >= deadline:
                self._status("    Query timed out")
                break

            for characteristic in ALL_CHARACTERISTICS:
                expired = self.tracker.expire_in_flight(
                    characteristic, request_timeout_s or 0
                )
                if expired is not None:
                    self._status(f"    Request timed out on {characteristic}")
                request = self.tracker.take_next(characteristic)
                if request is not None:
                    self.device.write_command(
                        SERVICE_UUID, characteristic, request
                    )
            time.sleep(COMMAND_POLL_INTERVAL_S)

        time.sleep(settle_s if settle_s is not None else NOTIFICATION_SETTLE_S)

    # -- notification handlers ---------------------------------------------

    def _handle_info_notification(self, data: bytes) -> None:
        request = self.tracker.take_response_request(DEVICE_INFO_CHARACTERISTIC)
        parsed = self._safe_parse(DEVICE_INFO_CHARACTERISTIC, data, request)
        self._on_info(data, parsed)
        self._on_raw(DEVICE_INFO_CHARACTERISTIC, request, data, parsed)

    def _handle_ssc_notification(self, data: bytes) -> None:
        request = self.tracker.take_response_request(SSC_CHARACTERISTIC)
        parsed = self._safe_parse(SSC_CHARACTERISTIC, data, request)
        self._on_ssc(data, parsed)
        self._on_raw(SSC_CHARACTERISTIC, request, data, parsed)

    def _safe_parse(
        self,
        characteristic: str,
        data: bytes,
        request: bytes | None,
    ) -> object | None:
        """Parse one response without letting a malformed packet kill the thread."""
        try:
            return parse_response(characteristic, data, request, self.options)
        except Exception:  # noqa: BLE001 - daemon must survive malformed packets
            logger.exception("Failed to parse %s notification", characteristic)
            return None