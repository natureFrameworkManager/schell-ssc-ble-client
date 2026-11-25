"""Configuration for the read-only SSC web service."""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("/etc/ssc-web.toml")
DEFAULT_DATABASE_PATH = "/var/lib/ssc-recorder/ssc.sqlite3"


@dataclass(frozen=True, slots=True)
class WebConfig:
    database: str = DEFAULT_DATABASE_PATH
    host: str = "127.0.0.1"
    port: int = 8000
    root_path: str = ""

    raw_eeprom_download: bool = False
    default_range_days: int = 30
    max_presence_intervals: int = 5000
    max_history_points: int = 5000
    max_export_rows: int = 200000

    basic_auth_user: str | None = None
    basic_auth_password_env: str = "SSC_WEB_PASSWORD"

    def validated(self) -> WebConfig:
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.default_range_days <= 0:
            raise ValueError("default_range_days must be greater than zero")
        if (
            self.max_presence_intervals <= 0
            or self.max_history_points <= 0
            or self.max_export_rows <= 0
        ):
            raise ValueError("limits must be greater than zero")
        return self

    @property
    def basic_auth_password(self) -> str | None:
        if not self.basic_auth_user:
            return None
        password = os.environ.get(self.basic_auth_password_env)
        if not password:
            raise RuntimeError(
                f"basic_auth_user is set but {self.basic_auth_password_env} "
                "is empty"
            )
        return password


def _bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def load_config(
    path: str | os.PathLike[str] | None = None,
    *,
    database: str | None = None,
    host: str | None = None,
    port: int | None = None,
    raw_eeprom: bool | None = None,
) -> WebConfig:
    """Load TOML/env configuration, apply explicit overrides and validate."""
    config = WebConfig()
    env_path = os.environ.get("SSC_WEB_CONFIG")
    config_path = Path(path or env_path) if (path or env_path) else DEFAULT_CONFIG_PATH

    if config_path.exists():
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
        section = data.get("web", {})
        if not isinstance(section, dict):
            raise ValueError("[web] must be a TOML table")
        config = replace(
            config,
            database=str(section.get("database", config.database)),
            host=str(section.get("host", config.host)),
            port=_int(section.get("port"), config.port),
            root_path=str(section.get("root_path", config.root_path)),
            raw_eeprom_download=_bool(
                section.get("raw_eeprom_download"), config.raw_eeprom_download
            ),
            default_range_days=_int(
                section.get("default_range_days"), config.default_range_days
            ),
            max_presence_intervals=_int(
                section.get("max_presence_intervals"),
                config.max_presence_intervals,
            ),
            max_history_points=_int(
                section.get("max_history_points"), config.max_history_points
            ),
            max_export_rows=_int(
                section.get("max_export_rows"), config.max_export_rows
            ),
            basic_auth_user=section.get("basic_auth_user") or config.basic_auth_user,
            basic_auth_password_env=str(
                section.get(
                    "basic_auth_password_env", config.basic_auth_password_env
                )
            ),
        )
    elif path is not None:
        logger.warning("Web config %s does not exist; using defaults", config_path)

    env_database = os.environ.get("SSC_WEB_DATABASE")
    env_raw = os.environ.get("SSC_WEB_RAW_EEPROM")

    if env_database:
        config = replace(config, database=env_database)
    if env_raw is not None:
        config = replace(config, raw_eeprom_download=_bool(env_raw, False))
    if database is not None:
        config = replace(config, database=database)
    if host is not None:
        config = replace(config, host=host)
    if port is not None:
        config = replace(config, port=port)
    if raw_eeprom is not None:
        config = replace(config, raw_eeprom_download=raw_eeprom)

    return config.validated()