"""Base class for configuration panels.

A panel builds field rows, wires their editors to a `ConfigStore` section, and
refreshes itself when the configuration changes elsewhere (undo, project open).

The `_loading` guard matters: without it, programmatically setting a widget
value during a refresh emits a change signal, which writes back to the store,
which emits `configChanged`, which refreshes the panel again. The guard turns
that potential loop into a one-way update.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from aops.controller.config_store import ConfigStore
from aops.core.config import AopsConfig
from aops.core.stats import DerivedGeometry
from aops.core.validation import ValidationReport
from aops.resources.field_levels import UiLevel, visible_at
from aops.resources.glossary import hint_for
from aops.ui.widgets.field_row import COMBO_VALUES, FieldRow, connect_editor


class ConfigPanel(QWidget):
    """A group of field rows bound to one configuration section."""

    section: str = ""

    def __init__(self, store: ConfigStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._rows: dict[str, FieldRow] = {}
        self._loading = False
        #: Current filter text and mode, so either can be changed independently
        #: without the other being forgotten.
        self._filter = ""
        self._mode = UiLevel.ADVANCED

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(1)

        self.build()

    # -- construction -------------------------------------------------------

    def build(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def add_row(
        self,
        field: str,
        label: str,
        editor: QWidget,
        *,
        suffix: str = "",
        tooltip: str = "",
        section: str | None = None,
    ) -> FieldRow:
        """Add a field row and bind its editor back to the store.

        A row with no explicit tooltip falls back to the shared hint registry,
        so every field is explained from one place and a panel only spells one
        out inline when it has something more contextual to say.
        """
        path = f"{section or self.section}.{field}"
        row = FieldRow(
            label, editor, path, suffix=suffix, tooltip=tooltip or hint_for(path), parent=self
        )
        self._rows[path] = row
        self._layout.addWidget(row)

        target_section = section or self.section

        def on_change(value: Any) -> None:
            if self._loading:
                return
            self._store.update_section(target_section, **{field: value})

        connect_editor(editor, on_change)
        return row

    def add_readout(
        self, label: str, editor: QWidget, *, suffix: str = "", tooltip: str = ""
    ) -> FieldRow:
        """Add a display-only row.

        Deliberately NOT bound to a config field and NOT connected to any change
        signal. Binding a read-only editor would be actively harmful: `setText`
        during a refresh emits `textChanged`, which would write back to a config
        field that does not exist.
        """
        row = FieldRow(label, editor, "", suffix=suffix, tooltip=tooltip, parent=self)
        self._layout.addWidget(row)
        return row

    def add_note(self, text: str) -> QLabel:
        note = QLabel(text, self)
        note.setProperty("sectionCaption", True)
        note.setWordWrap(True)
        self._layout.addWidget(note)
        return note

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    # -- refresh ------------------------------------------------------------

    def refresh(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        """Push configuration values back into the widgets."""
        self._loading = True
        try:
            self.load(cfg, derived)
        finally:
            self._loading = False

    def load(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        """Default: mirror each bound field from the config onto its editor."""
        for path, row in self._rows.items():
            section_name, field = path.split(".", 1)
            section_obj = getattr(cfg, section_name, None)
            if section_obj is None or not hasattr(section_obj, field):
                continue
            _set_editor_value(row.editor, getattr(section_obj, field))

    def apply_validation(self, report: ValidationReport) -> None:
        for path, row in self._rows.items():
            row.apply_findings(report.for_field(path))

    def focus_field(self, path: str) -> bool:
        row = self._rows.get(path)
        if row is None:
            return False
        row.editor.setFocus()
        return True

    def apply_filter(self, needle: str) -> int:
        """Show only rows matching `needle`, within the current mode."""
        return self.refresh_visibility(needle, self._mode)

    def apply_level(self, mode: UiLevel) -> int:
        """Show only rows belonging to `mode`, honouring any active filter."""
        return self.refresh_visibility(self._filter, mode)

    def refresh_visibility(self, needle: str, mode: UiLevel) -> int:
        """Show rows that both match the filter and belong to the mode.

        The two constraints compose rather than override: filtering inside
        Simple mode searches what Simple mode shows, which is what a user who
        chose Simple would expect. Returns how many rows survived.

        Non-row widgets (notes, buttons, readouts) are hidden while a filter is
        active - leaving a stray "Apply measurement" button under three matched
        rows reads as though it belongs to them - and in Simple mode they follow
        the section, since a section with nothing left to show should show
        nothing at all.
        """
        self._filter = needle = needle.strip().lower()
        self._mode = mode

        matches = 0
        for path, row in self._rows.items():
            visible = row.matches(needle) and visible_at(path, mode)
            row.setVisible(visible)
            matches += int(visible)

        bound = set(self._rows.values())
        extras_visible = not needle and matches > 0
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is not None and widget not in bound:
                widget.setVisible(extras_visible)

        return matches

    def simple_row_count(self) -> int:
        """How many of this panel's rows Simple mode shows."""
        return sum(1 for path in self._rows if visible_at(path, UiLevel.SIMPLE))

    def rows(self) -> dict[str, FieldRow]:
        return dict(self._rows)

    def set_row_enabled(self, path: str, enabled: bool) -> None:
        """Grey out a row whose controlling switch is off.

        Left live, "Ruler position: below" invites the user to adjust a ruler
        that is not being printed and then wonder why nothing changed.
        """
        row = self._rows.get(path)
        if row is not None:
            row.setEnabled(enabled)


def _set_editor_value(editor: QWidget, value: Any) -> None:
    """Set an editor's value without triggering user-edit side effects."""
    if isinstance(editor, QDoubleSpinBox):
        if abs(editor.value() - float(value)) > 1e-9:
            editor.setValue(float(value))
    elif isinstance(editor, QSpinBox):
        if editor.value() != int(value):
            editor.setValue(int(value))
    elif isinstance(editor, QComboBox):
        values = getattr(editor, COMBO_VALUES, None)
        if values is not None and value in values:
            index = values.index(value)
        else:
            index = editor.findData(value)
        if index >= 0 and index != editor.currentIndex():
            editor.setCurrentIndex(index)
    elif isinstance(editor, QCheckBox):
        if editor.isChecked() != bool(value):
            editor.setChecked(bool(value))
    elif isinstance(editor, QLineEdit):
        # Read-only editors are display-only readouts written by their panel's
        # own `load`, never mirrored from a config field.
        if editor.isReadOnly() or editor.text() == str(value):
            return
        # Preserve the caret so a refresh mid-typing does not jump the cursor.
        cursor = editor.cursorPosition()
        editor.setText(str(value))
        editor.setCursorPosition(min(cursor, len(editor.text())))
    elif isinstance(editor, QPlainTextEdit) and editor.toPlainText() != str(value):
        editor.setPlainText(str(value))


def enum_items(enum_cls: type, labels: Callable[[Any], str] | None = None) -> list[tuple[str, Any]]:
    """Build combo entries for a StrEnum, using `display_name` where available."""
    out: list[tuple[str, Any]] = []
    for member in enum_cls:
        if labels is not None:
            text = labels(member)
        elif hasattr(member, "display_name"):
            text = member.display_name
        else:
            text = str(member.value).replace("_", " ").capitalize()
        out.append((text, member))
    return out
