"""Recorder configuration loaded from TOML."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("/etc/ssc-recorder/recorder.toml")
DEFAULT_DATABASE_PATH = "/var/lib/ssc-recorder/ssc.sqlite3"


@dataclass(frozen=True, slots=True)
class RecorderConfig:
    """All runtime options of the recorder."""

    interval_s: float = 30.0
    scan_duration_s: int = 5
    offline_after_misses: int = 3
    max_query_attempts: int = 3
    query_timeout_s: float = 300.0
    request_timeout_s: float = 5.0
    info_settle_s: float = 2.0
    requery_interval_s: float = 0.0

    database: str = DEFAULT_DATABASE_PATH
    adapter: str | None = None
    record_empty_scans: bool = False
    presence_sample_mode: str = "every_scan"
    eeprom_start: int = 0x0000
    eeprom_end: int = 0x3FFF
    redact_secrets: bool = True
    log_level: str = "INFO"

    def validated(self) -> RecorderConfig:
        if self.interval_s <= 0:
            raise ValueError("interval_s must be greater than zero")
        if self.scan_duration_s <= 0:
            raise ValueError("scan_duration_s must be greater than zero")
        if self.offline_after_misses < 1:
            raise ValueError("offline_after_misses must be at least 1")
        if self.max_query_attempts < 1:
            raise ValueError("max_query_attempts must be at least 1")
        if self.query_timeout_s <= 0 or self.request_timeout_s <= 0:
            raise ValueError("query/request timeouts must be greater than zero")
        if self.eeprom_end < self.eeprom_start:
            raise ValueError("eeprom_end must not be smaller than eeprom_start")
        if self.presence_sample_mode not in {"every_scan", "session"}:
            raise ValueError("presence_sample_mode must be 'every_scan' or 'session'")
        return self


def _number(value: Any, default: float) -> float:
    if value is None:
        return default
    return float(value)


def _integer(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text, 0)


def _boolean(value: Any, default: bool) -> bool:
    return default if value is None else bool(value)


def load_config(
    path: str | Path | None = None,
    *,
    database: str | None = None,
    interval_s: float | None = None,
    scan_duration_s: int | None = None,
    adapter: str | None = None,
    log_level: str | None = None,
) -> RecorderConfig:
    """Load the TOML config, apply CLI overrides and validate it."""
    config = RecorderConfig()
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH

    if config_path.exists():
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
        section = data.get("recorder", {})
        if not isinstance(section, dict):
            raise ValueError("[recorder] must be a TOML table")

        config = replace(
            config,
            interval_s=_number(section.get("interval_s"), config.interval_s),
            scan_duration_s=_integer(
                section.get("scan_duration_s"), config.scan_duration_s
            ),
            offline_after_misses=_integer(
                section.get("offline_after_misses"), config.offline_after_misses
            ),
            max_query_attempts=_integer(
                section.get("max_query_attempts"), config.max_query_attempts
            ),
            query_timeout_s=_number(
                section.get("query_timeout_s"), config.query_timeout_s
            ),
            request_timeout_s=_number(
                section.get("request_timeout_s"), config.request_timeout_s
            ),
            info_settle_s=_number(section.get("info_settle_s"), config.info_settle_s),
            requery_interval_s=_number(
                section.get("requery_interval_s"), config.requery_interval_s
            ),
            database=str(section.get("database", config.database)),
            adapter=section.get("adapter") or config.adapter,
            record_empty_scans=_boolean(
                section.get("record_empty_scans"), config.record_empty_scans
            ),
            presence_sample_mode=str(
                section.get("presence_sample_mode", config.presence_sample_mode)
            ),
            eeprom_start=_integer(section.get("eeprom_start"), config.eeprom_start),
            eeprom_end=_integer(section.get("eeprom_end"), config.eeprom_end),
            redact_secrets=_boolean(
                section.get("redact_secrets"), config.redact_secrets
            ),
            log_level=str(section.get("log_level", config.log_level)),
        )
    elif path is not None:
        logger.warning("Config file %s does not exist; using defaults", config_path)

    if database is not None:
        config = replace(config, database=database)
    if interval_s is not None:
        config = replace(config, interval_s=interval_s)
    if scan_duration_s is not None:
        config = replace(config, scan_duration_s=scan_duration_s)
    if adapter is not None:
        config = replace(config, adapter=adapter)
    if log_level is not None:
        config = replace(config, log_level=log_level)

    return config.validated()