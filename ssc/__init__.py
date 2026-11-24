"""BLE client for Schell SSC (SE2) sanitary fittings.

Layers, from bottom to top (imports only ever point downwards):

    codecs / constants / config / types
        protocol.frames
        advertisement, telemetry, firmware, bits, stats, eeprom
        notifications
        ble.tracker, ble.session
        db.models, db.engine, db.repository
        recorder.*, web.*, cli.main, cli.display, cli.prompts

Only :mod:`ssc.ble` imports ``simplepyble``; only :mod:`ssc.cli`,
:mod:`ssc.recorder.runner` and :mod:`ssc.web` write to stdout or read from
stdin.
"""

__all__ = [
    "advertisement",
    "bits",
    "codecs",
    "config",
    "constants",
    "db",
    "eeprom",
    "firmware",
    "notifications",
    "recorder",
    "stats",
    "telemetry",
    "types",
    "web",
]