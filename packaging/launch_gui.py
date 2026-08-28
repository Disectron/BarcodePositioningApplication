"""PyInstaller entry script for the windowed AOPS.exe.

Exists because a spec file wants a script, not a module path. Everything real
lives in `aops.app`.
"""

import sys

from aops.app import main

sys.exit(main())
