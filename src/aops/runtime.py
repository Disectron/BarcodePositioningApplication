"""Frozen-build awareness: paths and crash reporting for the packaged .exe.

A PyInstaller build changes two things the source tree takes for granted:
where data files live, and what happens when the program dies. `resource_path`
answers the first for both worlds, so no caller ever asks "am I frozen?".
`install_crash_handler` answers the second: a windowed .exe has no console, so
an unhandled exception would otherwise vanish - the machine builder would see
the app close and nothing else. The handler writes a full traceback to a log
file the user can send back, and tells them where it went.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def resource_path(relative: str) -> Path:
    """Absolute path of a bundled data file, frozen or not.

    `relative` is the path under ``src/`` (e.g. ``aops/ui/theme/aops.qss``);
    the PyInstaller spec collects data files under the same relative layout,
    so one expression serves both worlds.
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / relative
    return Path(__file__).resolve().parent.parent / relative


def crash_log_dir() -> Path:
    """Where crash logs go: a per-user, always-writable directory.

    The install directory is not it - Program Files is read-only to the
    running user, which is exactly the kind of thing that makes a crash
    handler crash.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "AOPS" / "logs"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "aops"


def write_crash_log(exc_type: type[BaseException], exc: BaseException, tb: object) -> Path | None:
    """Append the traceback to today's crash log. Returns the path, or None
    when even logging failed - the handler must never raise."""
    try:
        directory = crash_log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"crash-{datetime.now(UTC):%Y%m%d}.log"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n--- {datetime.now(UTC).isoformat()} ---\n")
            from aops import __version__

            fh.write(f"AOPS {__version__} frozen={is_frozen()} python={sys.version}\n")
            fh.write("".join(traceback.format_exception(exc_type, exc, tb)))
        return path
    except Exception:
        return None


def install_crash_handler() -> None:
    """Route unhandled exceptions to a log file plus a best-effort dialog.

    Installed by the GUI entry point. The original hook still runs, so a
    console launch (or a test harness) keeps its normal traceback.
    """
    previous = sys.excepthook

    def hook(exc_type: type[BaseException], exc: BaseException, tb: object) -> None:
        path = write_crash_log(exc_type, exc, tb)
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                where = f"\n\nDetails were written to:\n{path}" if path else ""
                QMessageBox.critical(
                    None,
                    "AOPS - unexpected error",
                    f"AOPS hit an unexpected error and may be unstable.{where}",
                )
        except Exception:
            pass
        previous(exc_type, exc, tb)

    sys.excepthook = hook
