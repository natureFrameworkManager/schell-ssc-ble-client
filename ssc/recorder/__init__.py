"""Long-running SSC presence and state recorder.

The recorder scans for SSC devices, records when they are seen, and queries a
device's complete state once per offline-to-online transition.  Devices are
discovered dynamically and stored in the database the first time they appear;
there is no static device list.
"""

from __future__ import annotations

from ssc.recorder.config import RecorderConfig, load_config

__all__ = ["RecorderConfig", "load_config"]