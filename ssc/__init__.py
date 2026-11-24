"""BLE client for Schell SSC (SE2) sanitary fittings.

Layers, from bottom to top (imports only ever point downwards):

    codecs / constants / config / types
        protocol.frames
        advertisement, telemetry, firmware, bits, stats, eeprom
        notifications
        ble.tracker, ble.session
        cli.main, cli.display, cli.prompts

Only :mod:`ssc.ble` imports ``simplepyble``; only :mod:`ssc.cli` writes to
stdout or reads from stdin.
"""

__all__ = [
    "advertisement",
    "bits",
    "codecs",
    "config",
    "constants",
    "firmware",
    "notifications",
    "stats",
    "telemetry",
    "types",
]