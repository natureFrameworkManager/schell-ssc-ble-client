"""Allow ``python -m ssc``."""

from __future__ import annotations

import sys

from ssc.cli.main import main

if __name__ == "__main__":
    sys.exit(main())