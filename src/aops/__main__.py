"""``python -m aops`` launches the GUI.

Use ``python -m aops.cli`` (or the ``aops`` console script) for headless work.
"""

from __future__ import annotations

from aops.app import main

if __name__ == "__main__":
    raise SystemExit(main())
