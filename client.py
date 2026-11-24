"""Compatibility entry point: ``python client.py``.

The implementation lives in the :mod:`ssc` package; see ``ssc/cli/main.py``.
Equivalent invocations::

    python client.py
    python -m ssc
    ssc                     # after ``pip install -e .``
"""

from __future__ import annotations

import sys

from ssc.cli.main import main

if __name__ == "__main__":
    sys.exit(main())