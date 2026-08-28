"""PyInstaller entry script for the console aops-cli.exe."""

import sys

from aops.cli import main

sys.exit(main())
