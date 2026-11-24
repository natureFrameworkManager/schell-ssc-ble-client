"""Command line entry point: adapter selection, scan, connect and query."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from ssc.ble.adapters import (
    endpoint_label,
    get_adapters,
    select_adapter,
    selectable_adapters,
)
from ssc.ble.scanner import scan, ssc_devices, unknown_devices
from ssc.ble.session import Session
from ssc.cli import display, prompts
from ssc.config import Options
from ssc.constants import EEPROM_DUMP_END, EEPROM_DUMP_START
from ssc.protocol.frames import build_eeprom_dump_plan

LOGGER_NAME = "ssc"


def build_parser() -> argparse.ArgumentParser:
    """Command line flags; the defaults match the old module level constants."""
    parser = argparse.ArgumentParser(
        prog="ssc",
        description="Scan for Schell SSC devices and dump their EEPROM.",
    )
    parser.add_argument(
        "--scan-duration",
        type=int,
        default=2,
        metavar="SECONDS",
        help="scan duration in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--scan-debug-ssc",
        action="store_true",
        help="report SSC devices during the scan and print verbose details",
    )
    parser.add_argument(
        "--show-unknown",
        action="store_true",
        help="also report and display non-SSC devices",
    )
    parser.add_argument(
        "--show-telemetry",
        action="store_true",
        help="print telemetry notifications",
    )
    parser.add_argument(
        "--debug-bytes",
        action="store_true",
        help="log all raw and built byte streams",
    )
    parser.add_argument(
        "--debug-eeprom",
        action="store_true",
        help="log EEPROM extraction details",
    )
    parser.add_argument(
        "--warnings-eeprom",
        action="store_true",
        help="warn about EEPROM segments that do not fit a response",
    )
    return parser


def options_from_args(args: argparse.Namespace) -> Options:
    """Turn parsed command line arguments into :class:`Options`."""
    return Options(
        scan_duration_s=args.scan_duration,
        scan_debug_ssc=args.scan_debug_ssc,
        scan_show_unknown=args.show_unknown,
        show_telemetry=args.show_telemetry,
        debug_bytes=args.debug_bytes,
        debug_eeprom=args.debug_eeprom,
        warnings_eeprom=args.warnings_eeprom,
    )


def configure_logging(options: Options) -> None:
    """Route the package loggers to stderr, honouring the debug switches.

    Debug verbosity is a logging concern; the ``warnings_eeprom`` switch is
    passed to the decoder through :class:`~ssc.config.Options` instead.
    """
    package_logger = logging.getLogger(LOGGER_NAME)
    if not package_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        package_logger.addHandler(handler)
    package_logger.setLevel(logging.DEBUG if options.debug_bytes else logging.INFO)

    eeprom_logger = logging.getLogger("ssc.eeprom")
    if options.debug_logging:
        eeprom_logger.setLevel(logging.DEBUG)
    else:
        eeprom_logger.setLevel(logging.NOTSET)  # inherit the package level


def main(argv: Sequence[str] | None = None) -> int:
    """Run the client; returns the process exit code."""
    args = build_parser().parse_args(argv)
    options = options_from_args(args)
    configure_logging(options)

    adapters = get_adapters()
    if not adapters:
        print("No adapters found")
        return 1
    if not selectable_adapters(adapters):
        print("Only test adapter found")
        return 1

    adapter = select_adapter(adapters, prompts.ask_adapter)
    if adapter is None:
        print("No valid adapter selected")
        return 1
    print(f"Using adapter: {endpoint_label(adapter)}")

    print(f"Scan for {options.scan_duration_s} seconds")
    devices = scan(
        adapter,
        options.scan_duration_s,
        on_start=lambda: print("Scan started"),
        on_stop=lambda: print("Scan stopped"),
        on_found=lambda peripheral: display.scan_found(peripheral, options),
    )

    found_ssc = ssc_devices(devices)
    print(f"Found {len(devices)} devices, including {len(found_ssc)} SSC devices")
    for device in found_ssc:
        display.display_ssc_device(device, options)
    if options.scan_show_unknown:
        for device in unknown_devices(devices):
            display.display_unknown_device(device)

    if not found_ssc:
        print("No SSC devices found")
        return 1

    selected = prompts.ask_devices(found_ssc)
    on_info, on_ssc = display.notification_handlers(options)
    commands = build_eeprom_dump_plan(EEPROM_DUMP_START, EEPROM_DUMP_END)

    for device in selected:
        try:
            print(f"Connecting to {endpoint_label(device)}")
            device.connect()
            session = Session(
                device,
                options,
                on_status=print,
                on_info=on_info,
                on_ssc=on_ssc,
            )
            session.query(commands)
        except Exception as exc:  # noqa: BLE001 - continue with the next device
            print(f"Failed to connect to {endpoint_label(device)}: {exc}")
        finally:
            if device.is_connected():
                device.disconnect()

    return 0