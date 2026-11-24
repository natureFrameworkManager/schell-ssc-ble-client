"""SQLite persistence for the SSC recorder.

The database layer is deliberately independent of Bluetooth and the CLI:
:mod:`ssc.db.models` contains only SQLModel table definitions and
:mod:`ssc.db.engine` / :mod:`ssc.db.repository` contain the SQLite plumbing.
"""

from __future__ import annotations

from ssc.db.models import (
    CalendarSlot,
    ConfigChange,
    ConfigFieldValue,
    DailyStat,
    Device,
    EepromImage,
    EventLogEntry,
    FirmwareState,
    LifetimeStatsState,
    ModuleInfoState,
    OffPeriod,
    OnlinePeriod,
    PresenceSample,
    RecorderRun,
    ScanRun,
    StateSnapshot,
    TelemetryState,
    TodayStatsState,
)

__all__ = [
    "CalendarSlot",
    "ConfigChange",
    "ConfigFieldValue",
    "DailyStat",
    "Device",
    "EepromImage",
    "EventLogEntry",
    "FirmwareState",
    "LifetimeStatsState",
    "ModuleInfoState",
    "OffPeriod",
    "OnlinePeriod",
    "PresenceSample",
    "RecorderRun",
    "ScanRun",
    "StateSnapshot",
    "TelemetryState",
    "TodayStatsState",
]