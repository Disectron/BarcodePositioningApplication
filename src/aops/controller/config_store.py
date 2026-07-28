"""Holds the current configuration and the undo/redo history.

The only mutable application state lives here. Because `AopsConfig` is a frozen
dataclass, every edit produces a new immutable value, undo/redo is just a list
of those values, and handing a snapshot to an export thread is free and safe.

`configChanged` carries the set of changed dotted paths so the controller can
skip work: editing the engineer's name should not re-encode 421 symbols.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from PySide6.QtCore import QObject, Signal

from aops.core.config import AopsConfig

MAX_HISTORY = 100


def _changed_paths(old: AopsConfig, new: AopsConfig) -> frozenset[str]:
    """Dotted paths of fields that differ between two configurations."""
    changed: set[str] = set()
    for section in dataclasses.fields(AopsConfig):
        a = getattr(old, section.name)
        b = getattr(new, section.name)
        if a == b:
            continue
        if dataclasses.is_dataclass(a):
            for f in dataclasses.fields(a):
                if getattr(a, f.name) != getattr(b, f.name):
                    changed.add(f"{section.name}.{f.name}")
        else:
            changed.add(section.name)
    return frozenset(changed)


class ConfigStore(QObject):
    """Owns the configuration and emits changes."""

    configChanged = Signal(object, object)  # (AopsConfig, frozenset[str])
    dirtyChanged = Signal(bool)
    pathChanged = Signal(object)  # str | None

    def __init__(self, config: AopsConfig | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config or AopsConfig()
        self._undo: list[AopsConfig] = []
        self._redo: list[AopsConfig] = []
        self._dirty = False
        self._path: str | None = None

    # -- state --------------------------------------------------------------

    @property
    def config(self) -> AopsConfig:
        return self._config

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def path(self) -> str | None:
        return self._path

    def set_path(self, path: str | None) -> None:
        self._path = path
        self.pathChanged.emit(path)

    def _set_dirty(self, value: bool) -> None:
        if self._dirty != value:
            self._dirty = value
            self.dirtyChanged.emit(value)

    # -- editing ------------------------------------------------------------

    def update_section(self, section: str, **changes: Any) -> None:
        """Replace fields within one config section."""
        current = getattr(self._config, section)
        updated = dataclasses.replace(current, **changes)
        if updated == current:
            return
        self._commit(dataclasses.replace(self._config, **{section: updated}))

    def update_sections(self, **sections: dict[str, Any]) -> None:
        """Replace fields across several sections as a single undoable edit.

        Applying a print style touches both `output` and `printing`. Doing that
        as two `update_section` calls would put two entries on the undo stack,
        so one Ctrl+Z would leave the configuration in a state that matches no
        style at all.
        """
        updated = self._config
        for name, changes in sections.items():
            current = getattr(updated, name)
            updated = dataclasses.replace(
                updated, **{name: dataclasses.replace(current, **changes)}
            )
        if updated == self._config:
            return
        self._commit(updated)

    def set_config(self, config: AopsConfig, *, mark_clean: bool = False) -> None:
        """Replace the whole configuration (project open, or New)."""
        self._undo.append(self._config)
        self._redo.clear()
        old = self._config
        self._config = config
        if mark_clean:
            self._dirty = False
            self.dirtyChanged.emit(False)
        else:
            self._set_dirty(True)
        self.configChanged.emit(config, _changed_paths(old, config))

    def _commit(self, config: AopsConfig) -> None:
        self._undo.append(self._config)
        if len(self._undo) > MAX_HISTORY:
            self._undo.pop(0)
        self._redo.clear()
        old = self._config
        self._config = config
        self._set_dirty(True)
        self.configChanged.emit(config, _changed_paths(old, config))

    # -- history ------------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> None:
        if not self._undo:
            return
        self._redo.append(self._config)
        old = self._config
        self._config = self._undo.pop()
        self._set_dirty(True)
        self.configChanged.emit(self._config, _changed_paths(old, self._config))

    def redo(self) -> None:
        if not self._redo:
            return
        self._undo.append(self._config)
        old = self._config
        self._config = self._redo.pop()
        self._set_dirty(True)
        self.configChanged.emit(self._config, _changed_paths(old, self._config))

    def mark_saved(self) -> None:
        self._set_dirty(False)
