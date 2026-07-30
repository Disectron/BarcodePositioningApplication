"""Application preferences, stored via QSettings.

Kept strictly separate from the project file. Window geometry and the recent
file list describe *this installation*; they must not travel with a
commissioning project handed to a colleague.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, QStandardPaths

from aops.core.presets import PRESET_FILE_SUFFIX

ORGANISATION = "AOPS"
APPLICATION = "PositionStripGenerator"
MAX_RECENT = 8


class SettingsStore:
    """Thin typed wrapper over QSettings."""

    def __init__(self) -> None:
        self._settings = QSettings(ORGANISATION, APPLICATION)

    # -- window state -------------------------------------------------------

    def save_window(self, geometry: QByteArray, state: QByteArray, splitter: QByteArray) -> None:
        self._settings.setValue("window/geometry", geometry)
        self._settings.setValue("window/state", state)
        self._settings.setValue("window/splitter", splitter)

    def window_geometry(self) -> QByteArray | None:
        return self._settings.value("window/geometry")

    def window_state(self) -> QByteArray | None:
        return self._settings.value("window/state")

    def splitter_state(self) -> QByteArray | None:
        return self._settings.value("window/splitter")

    # -- recent files -------------------------------------------------------

    def recent_files(self) -> list[str]:
        value = self._settings.value("recent/files", [])
        if isinstance(value, str):
            return [value]
        return [str(v) for v in (value or [])]

    def push_recent(self, path: str) -> None:
        files = [p for p in self.recent_files() if p != path]
        files.insert(0, path)
        self._settings.setValue("recent/files", files[:MAX_RECENT])

    # -- misc ---------------------------------------------------------------

    def last_export_dir(self) -> str:
        return str(self._settings.value("paths/export", ""))

    def set_last_export_dir(self, path: str) -> None:
        self._settings.setValue("paths/export", path)

    def last_project_dir(self) -> str:
        return str(self._settings.value("paths/project", ""))

    def set_last_project_dir(self, path: str) -> None:
        self._settings.setValue("paths/project", path)

    # -- interface ----------------------------------------------------------

    def ui_mode(self) -> str:
        """Last chosen configuration mode, as a UiLevel name."""
        return str(self._settings.value("ui/mode", "SIMPLE"))

    def set_ui_mode(self, name: str) -> None:
        self._settings.setValue("ui/mode", name)

    # -- presets ------------------------------------------------------------

    def presets_dir(self) -> Path:
        """Folder holding saved presets, created on first use.

        Deliberately a folder of readable files rather than blobs inside
        QSettings: a house standard is worth copying to a colleague, diffing
        after a change, or committing next to the PLC source.
        """
        root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        path = Path(root or ".") / "presets"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def list_presets(self) -> list[Path]:
        """Saved preset files, by name."""
        try:
            return sorted(self.presets_dir().glob(f"*{PRESET_FILE_SUFFIX}"))
        except OSError:
            return []

    def save_preset(self, name: str, text: str) -> Path:
        path = self.presets_dir() / f"{safe_filename(name)}{PRESET_FILE_SUFFIX}"
        path.write_text(text, encoding="utf-8")
        return path

    def delete_preset(self, path: Path) -> None:
        path.unlink(missing_ok=True)

    def sync(self) -> None:
        self._settings.sync()


def safe_filename(name: str) -> str:
    """Reduce a preset name to something every filesystem accepts.

    Presets are named by the user, and "4in roll / 300dpi" is a perfectly
    reasonable name that is not a legal filename anywhere.
    """
    cleaned = "".join(c if c.isalnum() or c in " -_" else "-" for c in name).strip()
    cleaned = " ".join(cleaned.split())
    return (cleaned or "preset")[:80]
