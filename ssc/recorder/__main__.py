"""Allow ``python -m ssc.recorder``."""

from __future__ import annotations

import sys

from ssc.recorder.runner import main

if __name__ == "__main__":
    sys.exit(main())