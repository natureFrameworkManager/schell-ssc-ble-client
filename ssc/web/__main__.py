"""Run the web service without installing the package.

Usage from the repository root::

    PYTHONPATH=. .venv/bin/python -m ssc.web --config deploy/ssc-web.toml
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

import uvicorn

from ssc.web.config import load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ssc-web",
        description="Read-only web UI and API for the SSC recorder database.",
    )
    parser.add_argument("--config", help="TOML web config file")
    parser.add_argument("--database", help="SQLite database path")
    parser.add_argument("--host", help="bind host")
    parser.add_argument("--port", type=int, help="bind port")
    parser.add_argument("--reload", action="store_true", help="development reload")
    parser.add_argument("--log-level", default="info", help="uvicorn log level")
    parser.add_argument(
        "--raw-eeprom",
        action="store_true",
        default=None,
        help="enable the protected raw EEPROM download endpoint",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(
            args.config,
            database=args.database,
            host=args.host,
            port=args.port,
            raw_eeprom=args.raw_eeprom,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Invalid web configuration: {exc}", file=sys.stderr)
        return 2

    os.environ["SSC_WEB_DATABASE"] = config.database
    if args.config:
        os.environ["SSC_WEB_CONFIG"] = str(args.config)
    os.environ["SSC_WEB_RAW_EEPROM"] = "1" if config.raw_eeprom_download else "0"

    uvicorn.run(
        "ssc.web.app:app",
        host=config.host,
        port=config.port,
        reload=args.reload,
        log_level=args.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())