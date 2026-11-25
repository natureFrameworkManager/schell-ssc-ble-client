"""Collection and assembly of one device query."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import threading
from typing import Any

from ssc.codecs import parse_version
from ssc.constants import CMD_READ_ARRAY, CMD_READ_EE_BY_ADDR, CMD_READ_MODULE_INFO
from ssc.eeprom.daily_stats import parse_today_stats
from ssc.eeprom.image import parse_eeprom_image
from ssc.firmware import parse_firmware
from ssc.stats import parse_lifetime_stats
from ssc.telemetry import parse_telemetry

logger = logging.getLogger(__name__)


class EepromAssembler:
    """Assemble 16-byte EEPROM read responses into one image."""

    def __init__(self, start_address: int, end_address: int) -> None:
        if end_address < start_address:
            raise ValueError("end_address must not be smaller than start_address")
        self.start_address = start_address
        self.end_address = end_address
        self.length = end_address - start_address + 1
        self.image = bytearray([0xFF]) * self.length
        self.written = bytearray(self.length)
        self._coverage = 0

    def add_response(self, request: bytes | None, data: bytes) -> bool:
        if (
            len(data) < 2
            or data[0] != len(data)
            or data[1] != CMD_READ_EE_BY_ADDR
        ):
            return False
        if request is None or len(request) < 4:
            return False
        address = (request[2] << 8) | request[3]
        payload = data[2:]
        offset = address - self.start_address
        if offset < 0 or offset + len(payload) > self.length:
            logger.warning(
                "Ignoring EEPROM response outside 0x%04X..0x%04X",
                self.start_address,
                self.end_address,
            )
            return False
        for index, value in enumerate(payload):
            target = offset + index
            if not self.written[target]:
                self._coverage += 1
            self.image[target] = value
            self.written[target] = 1
        return True

    @property
    def coverage(self) -> int:
        return self._coverage

    @property
    def complete(self) -> bool:
        return self._coverage == self.length

    @property
    def sha256(self) -> str:
        return hashlib.sha256(bytes(self.image)).hexdigest()

    def missing_ranges(self) -> list[list[int]]:
        ranges: list[list[int]] = []
        start: int | None = None
        for offset, flag in enumerate(self.written):
            if not flag:
                if start is None:
                    start = self.start_address + offset
            elif start is not None:
                ranges.append([start, self.start_address + offset - 1])
                start = None
        if start is not None:
            ranges.append([start, self.end_address])
        return ranges

    def as_bytes(self) -> bytes:
        return bytes(self.image)


class SnapshotCollector:
    """Collect all notification data belonging to one query.

    Methods are called from the BLE callback thread while the query is running;
    the assembled state is read by the main thread after the query returns.
    """

    def __init__(self, start_address: int, end_address: int) -> None:
        self.assembler = EepromAssembler(start_address, end_address)
        self.telemetry: dict[str, Any] | None = None
        self.firmware: dict[str, Any] | None = None
        self.module_info: dict[str, Any] | None = None
        self.lifetime: dict[str, Any] | None = None
        self.today: dict[str, Any] | None = None
        self.errors: list[str] = []
        self._lock = threading.Lock()

    def add_notification(
        self,
        characteristic: str,
        request: bytes | None,
        data: bytes,
        parsed: object | None,
    ) -> None:
        if len(data) < 2 or data[0] != len(data):
            return
        opcode = data[1]
        with self._lock:
            try:
                if opcode == CMD_READ_EE_BY_ADDR:
                    self.assembler.add_response(request, data)
                elif opcode == CMD_READ_ARRAY:
                    self._add_array(request, data[2:])
                elif opcode == CMD_READ_MODULE_INFO:
                    self._add_module_info(data[2:], request)
                if isinstance(parsed, dict):
                    self._add_parsed_fallback(parsed)
            except Exception as exc:  # noqa: BLE001 - keep the BLE callback alive
                logger.exception("Failed to collect notification")
                self.errors.append(str(exc))

    def _add_array(self, request: bytes | None, payload: bytes) -> None:
        """Collect an array response.

        Telemetry/firmware notifications carry a leading array index.  The
        consumption-stat responses are raw 8-byte chunks and must not be
        sliced.  Length checks keep unsolicited or truncated notifications out
        of the collector instead of raising ``IndexError``.
        """
        index = request[2] if request is not None and len(request) >= 3 else None

        if len(payload) >= 18 and payload[0] == 0x00:
            data = payload[1:]
            if len(data) >= 17:
                try:
                    self.telemetry = dict(parse_telemetry(data))
                except ValueError:
                    logger.debug("Ignoring invalid telemetry payload", exc_info=True)
                return

        if len(payload) >= 16 and payload[0] == 0x01:
            data = payload[1:]
            if len(data) >= 15:
                try:
                    self.firmware = dict(parse_firmware(data))
                except ValueError:
                    logger.debug("Ignoring invalid firmware payload", exc_info=True)
                return

        if index == 0x00:
            data = payload[1:] if payload[:1] == b"\x00" else payload
            if len(data) >= 17:
                try:
                    self.telemetry = dict(parse_telemetry(data))
                except ValueError:
                    logger.debug("Ignoring invalid telemetry payload", exc_info=True)
            return

        if index == 0x01:
            data = payload[1:] if payload[:1] == b"\x01" else payload
            if len(data) >= 15:
                try:
                    self.firmware = dict(parse_firmware(data))
                except ValueError:
                    logger.debug("Ignoring invalid firmware payload", exc_info=True)
            return

        if index in (0x06, 0x0B):
            data = (
                payload[1:]
                if len(payload) == 9 and payload[:1] == bytes((index,))
                else payload
            )
            if len(data) < 8:
                logger.debug(
                    "Ignoring short array response index=%s payload=%s",
                    index,
                    payload.hex(" "),
                )
                return
            try:
                if index == 0x06:
                    self.lifetime = dict(parse_lifetime_stats(data))
                else:
                    self.today = dict(parse_today_stats(data))
            except ValueError:
                logger.debug(
                    "Ignoring invalid stats payload index=%s", index, exc_info=True
                )
            return

        logger.debug(
            "Ignoring array response index=%s payload=%s",
            index,
            payload.hex(" "),
        )

    def _add_module_info(self, payload: bytes, request: bytes | None) -> None:
        if len(payload) >= 8:
            self.module_info = {
                "app_version": parse_version(payload[0:2]),
                "serial": payload[2:8],
            }
        elif request is not None and len(request) >= 16:
            self.module_info = {
                "app_version": parse_version(request[8:10]),
                "serial": request[10:16],
            }

    def _add_parsed_fallback(self, parsed: dict[str, Any]) -> None:
        if self.telemetry is None and "battery" in parsed and "datetime" in parsed:
            self.telemetry = parsed
        if self.firmware is None and "hardware_version" in parsed:
            self.firmware = parsed
        if self.lifetime is None and "count-restart" in parsed:
            self.lifetime = parsed
        if self.today is None and "count-normal" in parsed:
            self.today = parsed
        if self.module_info is None and "app_version" in parsed:
            self.module_info = parsed

    def parsed_state(self, reference_year: int | None = None) -> dict[str, Any]:
        """Parse the assembled state; safe to call after the query."""
        with self._lock:
            if reference_year is None and self.telemetry is not None:
                device_time = self.telemetry.get("datetime")
                if isinstance(device_time, dt.datetime):
                    reference_year = device_time.year

            if self.assembler.coverage:
                parsed = parse_eeprom_image(
                    self.assembler.as_bytes(),
                    start_address=self.assembler.start_address,
                    reference_year=reference_year,
                    written=self.assembler.written,
                )
            else:
                parsed = {
                    "config": {},
                    "calendar": [],
                    "events": [],
                    "daily_stats": [],
                    "missing_fields": [],
                }
            parsed.update(
                {
                    "telemetry": self.telemetry,
                    "firmware": self.firmware,
                    "module_info": self.module_info,
                    "lifetime": self.lifetime,
                    "today": self.today,
                    "device_datetime": (
                        self.telemetry.get("datetime") if self.telemetry else None
                    ),
                    "collector_errors": list(self.errors),
                }
            )
            return parsed