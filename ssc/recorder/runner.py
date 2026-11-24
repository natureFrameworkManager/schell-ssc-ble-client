"""Main recorder loop, CLI and systemd entry point."""

from __future__ import annotations

import argparse
import importlib.metadata
import logging
import signal
import socket
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path

import simplepyble
from sqlmodel import Session as DbSession
from sqlmodel import select

from ssc.ble.adapters import endpoint_label, ensure_powered, get_adapter
from ssc.ble.scanner import is_ssc_device, scan
from ssc.ble.session import Session
from ssc.config import Options
from ssc.db.engine import create_db_engine, init_db
from ssc.db.models import Device, OffPeriod, OnlinePeriod, StateSnapshot, utcnow
from ssc.db.repository import Repository
from ssc.recorder.collector import SnapshotCollector
from ssc.recorder.config import RecorderConfig, load_config
from ssc.recorder.query import (
    advertisement_identity,
    build_state_query_plan,
    read_advertisement,
    safe_rssi,
)
from ssc.recorder.state import DeviceRuntime, DiscoveredDevice, PresenceTracker

logger = logging.getLogger(__name__)


class Recorder:
    """Scan, presence tracking and one-time state queries."""

    def __init__(
        self,
        config: RecorderConfig,
        repository: Repository | None,
        *,
        run_id: int | None = None,
        dry_run: bool = False,
    ) -> None:
        self.config = config
        self.repository = repository
        self.run_id = run_id
        self.dry_run = dry_run
        self.tracker = (
            PresenceTracker(repository, config, run_id)
            if repository is not None
            else None
        )
        self.adapter: simplepyble.Adapter | None = None
        self._stop = threading.Event()

    # -- adapter / scan -----------------------------------------------------

    def ensure_adapter(self) -> bool:
        try:
            if self.adapter is not None and self.adapter.initialized():
                return True
        except Exception:  # noqa: BLE001 - stale adapter object
            self.adapter = None
        try:
            adapter = get_adapter(self.config.adapter)
            if adapter is None:
                logger.error(
                    "No selectable BLE adapter found (configured: %s)",
                    self.config.adapter or "auto",
                )
                self.adapter = None
                return False
            self.adapter = ensure_powered(adapter)
            logger.info("Using adapter: %s", endpoint_label(self.adapter))
            return True
        except Exception:  # noqa: BLE001 - adapter can disappear temporarily
            logger.exception("Could not acquire BLE adapter")
            self.adapter = None
            return False

    def discover(self) -> dict[str, DiscoveredDevice]:
        """Run one scan and return SSC devices keyed by BLE address."""
        if not self.ensure_adapter() or self.adapter is None:
            return {}
        try:
            peripherals = scan(self.adapter, self.config.scan_duration_s)
        except Exception:  # noqa: BLE001 - retry on the next cycle
            logger.exception("BLE scan failed")
            return {}

        found: dict[str, DiscoveredDevice] = {}
        for peripheral in peripherals:
            try:
                if not is_ssc_device(peripheral):
                    continue
                address = peripheral.address().upper()
                advertisement = read_advertisement(peripheral)
                serial, display_name, product = advertisement_identity(advertisement)
                rssi = safe_rssi(peripheral)
                battery_voltage = (
                    advertisement.get("battery_voltage")
                    if isinstance(advertisement, dict)
                    else None
                )
                battery_level = (
                    advertisement.get("battery_level")
                    if isinstance(advertisement, dict)
                    else None
                )
                discovered = DiscoveredDevice(
                    address=address,
                    peripheral=peripheral,
                    advertisement=advertisement,
                    rssi=rssi,
                    serial=serial,
                    display_name=display_name,
                    product=product,
                    battery_voltage_adv=int(battery_voltage * 10)
                    if isinstance(battery_voltage, (int, float))
                    else None,
                    battery_level=int(battery_level)
                    if isinstance(battery_level, (int, float))
                    else None,
                )
                previous = found.get(address)
                if previous is None or (rssi or -999) > (previous.rssi or -999):
                    found[address] = discovered
            except Exception:  # noqa: BLE001 - one malformed advertisement
                logger.debug("Could not inspect peripheral", exc_info=True)
        return found

    # -- cycle --------------------------------------------------------------

    def run_cycle(self) -> None:
        scan_started_at = utcnow()
        started_mono = time.monotonic()
        found = self.discover()

        if self.dry_run:
            for discovered in found.values():
                logger.info(
                    "Found SSC device %s (%s), rssi=%s",
                    discovered.address,
                    discovered.display_name or discovered.serial or "unnamed",
                    discovered.rssi,
                )
            return

        if self.repository is None or self.tracker is None:
            return

        needs_query: list[DeviceRuntime] = []
        for discovered in found.values():
            try:
                if self.tracker.observe(discovered, scan_started_at):
                    runtime = self.tracker.by_address.get(discovered.address)
                    if runtime is not None:
                        needs_query.append(runtime)
            except Exception:  # noqa: BLE001 - one device must not stop the cycle
                logger.exception(
                    "Could not record presence for %s", discovered.address
                )

        for runtime in list(self.tracker.runtimes.values()):
            if runtime.address not in found:
                try:
                    self.tracker.miss(runtime, scan_started_at)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Could not record absence for %s", runtime.address
                    )

        for runtime in needs_query:
            discovered = found.get(runtime.address)
            if discovered is not None:
                try:
                    self.query_device(runtime, discovered)
                except Exception:  # noqa: BLE001 - reported by query_device normally
                    logger.exception(
                        "Unexpected state query error for %s", discovered.address
                    )

        if self.config.record_empty_scans:
            finished_at = utcnow()
            self.repository.save_scan_run(
                recorder_run_id=self.run_id,
                started_at=scan_started_at,
                finished_at=finished_at,
                duration_ms=int((time.monotonic() - started_mono) * 1000),
                device_count=len(found),
                ssc_count=len(found),
                found_addresses=sorted(found),
            )

    def query_device(
        self,
        runtime: DeviceRuntime,
        discovered: DiscoveredDevice,
    ) -> None:
        """Connect, query the complete state once, and persist it."""
        if self.repository is None or runtime.online_period_id is None:
            return

        collector = SnapshotCollector(
            self.config.eeprom_start, self.config.eeprom_end
        )
        session = Session(
            discovered.peripheral,
            Options(warnings_eeprom=False),
            on_status=lambda message: logger.debug("BLE: %s", message),
            on_raw=collector.add_notification,
        )
        captured_at = utcnow()
        error: str | None = None

        logger.info(
            "Querying state of %s (attempt %s)",
            discovered.address,
            runtime.query_attempts + 1,
        )
        try:
            discovered.peripheral.connect()
            session.query_plan(
                build_state_query_plan(self.config),
                timeout_s=self.config.query_timeout_s,
                request_timeout_s=self.config.request_timeout_s,
                settle_s=self.config.info_settle_s,
            )
        except Exception as exc:  # noqa: BLE001 - daemon must continue
            error = str(exc)
            logger.exception("State query of %s failed", discovered.address)
        finally:
            try:
                if discovered.peripheral.is_connected():
                    discovered.peripheral.disconnect()
            except Exception:  # noqa: BLE001
                logger.debug("Disconnect failed", exc_info=True)

        completed_at = utcnow()
        if error is not None:
            status = self.tracker.query_failed(  # type: ignore[union-attr]
                runtime, completed_at, error=error
            )
            self.repository.update_online_query(
                runtime.online_period_id,
                status=status,
                attempts=runtime.query_attempts,
                queried_at=completed_at,
            )
            return

        try:
            parsed = collector.parsed_state()
            coverage = collector.assembler.coverage
            length = collector.assembler.length
            missing_ranges = collector.assembler.missing_ranges()
            collector_errors = list(collector.errors)
            status = "ok" if coverage == length and not collector_errors else "partial"
            if coverage == 0 and not any(
                parsed.get(key)
                for key in ("telemetry", "firmware", "lifetime", "today")
            ):
                status = "failed"

            self.repository.save_snapshot(
                device_id=runtime.device_id,
                online_period_id=runtime.online_period_id,
                captured_at=captured_at,
                completed_at=completed_at,
                image=collector.assembler.as_bytes() if coverage else None,
                start_address=self.config.eeprom_start,
                coverage=coverage,
                missing_ranges=missing_ranges if missing_ranges else None,
                parsed=parsed,
                query_status=status,
                error="; ".join(collector_errors) or None,
                redact_secrets=self.config.redact_secrets,
            )
            self.repository.update_online_query(
                runtime.online_period_id,
                status=status,
                attempts=runtime.query_attempts,
                queried_at=completed_at,
            )
        except Exception as exc:  # noqa: BLE001 - keep recording presence
            logger.exception("Could not store state snapshot for %s", discovered.address)
            status = self.tracker.query_failed(  # type: ignore[union-attr]
                runtime, completed_at, error=str(exc)
            )
            self.repository.update_online_query(
                runtime.online_period_id,
                status=status,
                attempts=runtime.query_attempts,
                queried_at=completed_at,
            )
            return

        if status == "failed":
            self.tracker.query_failed(  # type: ignore[union-attr]
                runtime, completed_at, error="no data received"
            )
        else:
            self.tracker.query_succeeded(runtime, completed_at)  # type: ignore[union-attr]
        logger.info(
            "Stored state snapshot for %s: %s, coverage %s/%s bytes",
            discovered.address,
            status,
            coverage,
            length,
        )

    # -- process lifecycle --------------------------------------------------

    def run(self, *, once: bool = False) -> None:
        if self.dry_run:
            self._loop(once=once)
            return

        if self.repository is None or self.tracker is None:
            raise RuntimeError("recorder repository is not initialized")

        run = self.repository.start_run(hostname(), package_version())
        self.run_id = run.id
        self.tracker.run_id = run.id
        self.repository.recover_after_restart(run.id)  # type: ignore[arg-type]
        self.tracker.load()

        try:
            self._loop(once=once)
        finally:
            reason = "once" if once else "shutdown"
            self.tracker.close_all(utcnow(), reason)
            self.repository.finish_run(run.id, reason)  # type: ignore[arg-type]

    def _loop(self, *, once: bool) -> None:
        next_scan = time.monotonic()
        while not self._stop.is_set():
            try:
                self.run_cycle()
            except Exception:  # noqa: BLE001 - keep the daemon alive
                logger.exception("Scan cycle failed")
                if once:
                    raise
            if once or self._stop.is_set():
                break

            next_scan += self.config.interval_s
            now = time.monotonic()
            if next_scan < now:
                # A full query can take longer than the scan interval.  Do not
                # start another scan immediately after an overrun.
                next_scan = now + 1.0
            self._stop.wait(max(0.0, next_scan - now))

    def stop(self) -> None:
        self._stop.set()


def hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def package_version() -> str:
    try:
        return importlib.metadata.version("schell-ssc-ble-client")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ssc-recorder",
        description=(
            "Record SSC device presence and query their complete state when "
            "they come online."
        ),
    )
    parser.add_argument("--config", type=Path, default=None, help="TOML config file")
    parser.add_argument("--database", help="SQLite database path")
    parser.add_argument("--interval", type=float, help="scan interval in seconds")
    parser.add_argument("--scan-duration", type=int, help="scan duration in seconds")
    parser.add_argument("--adapter", help="BLE adapter identifier or address")
    parser.add_argument("--log-level", help="DEBUG, INFO, WARNING, ...")
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one scan/query cycle and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="scan and log SSC devices without writing the database",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="print the recorded devices and open periods",
    )
    return parser


def print_status(database: str) -> int:
    if ":" not in database and not Path(database).exists():
        print(f"Database does not exist yet: {database}")
        return 0

    engine = create_db_engine(database)
    init_db(engine)
    with DbSession(engine) as session:
        devices = session.exec(select(Device).order_by(Device.id)).all()
        if not devices:
            print("No devices recorded yet")
            return 0
        for device in devices:
            online = session.exec(
                select(OnlinePeriod)
                .where(OnlinePeriod.device_id == device.id)
                .where(OnlinePeriod.ended_at.is_(None))
                .order_by(OnlinePeriod.started_at.desc())
            ).first()
            offline = session.exec(
                select(OffPeriod)
                .where(OffPeriod.device_id == device.id)
                .where(OffPeriod.ended_at.is_(None))
                .order_by(OffPeriod.started_at.desc())
            ).first()
            latest = session.exec(
                select(StateSnapshot)
                .where(StateSnapshot.device_id == device.id)
                .order_by(StateSnapshot.captured_at.desc())
            ).first()
            name = device.display_name or device.serial or device.address
            state = "online" if online else ("off" if offline else "unknown")
            print(f"{device.id}: {name} [{device.address}] {state}")
            if offline is not None:
                open_for = max(
                    0, int((utcnow() - offline.started_at).total_seconds())
                )
                print(
                    f"    off since {offline.started_at.isoformat()} "
                    f"({open_for}s)"
                )
            if latest is not None:
                print(
                    f"    last snapshot {latest.captured_at.isoformat()} "
                    f"({latest.query_status}, coverage {latest.coverage})"
                )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(
            args.config,
            database=args.database,
            interval_s=args.interval,
            scan_duration_s=args.scan_duration,
            adapter=args.adapter,
            log_level=args.log_level,
        )
    except (OSError, ValueError) as exc:
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        return 2

    configure_logging(config.log_level)
    logger.info("SSC recorder starting")

    if args.status:
        return print_status(config.database)

    if args.dry_run:
        recorder = Recorder(config, None, dry_run=True)
        recorder.run(once=args.once)
        return 0

    engine = create_db_engine(config.database)
    init_db(engine)
    repository = Repository(engine)
    recorder = Recorder(config, repository)

    def _stop(signum, frame) -> None:  # noqa: ANN001
        logger.info("Received signal %s; stopping", signum)
        recorder.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    try:
        recorder.run(once=args.once)
    except Exception:  # noqa: BLE001
        logger.exception("Recorder stopped with an error")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())