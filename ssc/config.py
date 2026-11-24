"""Runtime options.

Replaces the module level ``DEBUG_*`` / ``SCAN_*`` switches that used to be
spread over the top of ``client.py``.  The command line turns user flags into
this object; the debug switches only influence logging levels.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Options:
    """All user configurable behaviour of the client."""

    scan_duration_s: int = 2
    scan_debug_ssc: bool = False
    scan_show_unknown: bool = False
    show_telemetry: bool = False
    debug_bytes: bool = False
    debug_eeprom: bool = False
    warnings_eeprom: bool = True

    @property
    def debug_logging(self) -> bool:
        return self.debug_bytes or self.debug_eeprom