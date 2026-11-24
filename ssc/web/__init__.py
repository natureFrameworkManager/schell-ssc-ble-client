"""Read-only web UI and API for the SSC recorder database.

The web service is independent of :mod:`ssc.recorder`: it opens the same
SQLite database in read-only mode and never creates or migrates tables.
"""

from __future__ import annotations

from ssc.web.config import WebConfig, load_config

__all__ = ["WebConfig", "load_config"]