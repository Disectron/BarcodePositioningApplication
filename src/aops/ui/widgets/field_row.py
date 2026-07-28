"""Labelled field rows bound to configuration paths.

Each row knows its dotted config path, which is what lets a validation finding
put a coloured border and a tooltip on exactly the control that caused it,
rather than reporting "invalid geometry" somewhere far away from the cause.

Every numeric editor is created with keyboard tracking disabled. Without that,
typing "25" into a pitch box momentarily applies a pitch of 2 and triggers a
full recompute against a geometry the user never asked for.

Numeric editors also take two deliberate departures from stock Qt behaviour:

* **The wheel does not edit an unfocused box.** The whole configuration panel
  lives in a scroll area, and Qt's default is for a spin box under the pointer
  to swallow the wheel event. Scrolling past a column of spin boxes would
  silently change several values, which on this panel means silently changing
  the printed strip. An unfocused box now passes the event up to the scroll
  area; click or tab into it first to use the wheel.
* **Ctrl and Shift scale the step.** One step size never suits both "nudge the
  pitch by a hundredth" and "move it by ten millimetres", so Ctrl multiplies
  the step by ten and Shift divides it by ten, on the arrows and the wheel
  alike.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from aops.core.enums import Severity
from aops.core.validation import Finding

LABEL_WIDTH = 132

#: Shown once next to the filter box rather than on every tooltip.
STEP_HINT = "Ctrl = x10 step,  Shift = /10 step"


def _step_factor() -> float:
    """Multiplier applied to the single step by the held modifiers."""
    mods = QApplication.keyboardModifiers()
    factor = 1.0
    if mods & Qt.KeyboardModifier.ControlModifier:
        factor *= 10.0
    if mods & Qt.KeyboardModifier.ShiftModifier:
        factor /= 10.0
    return factor


class AopsDoubleSpinBox(QDoubleSpinBox):
    """Double spin box that ignores the wheel unless focused, and scales steps."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)

    def stepBy(self, steps: int) -> None:
        factor = _step_factor()
        if factor == 1.0:
            super().stepBy(steps)
            return
        base = self.singleStep()
        # A scaled step must still be representable at this many decimals, or
        # Shift would round to zero and the box would appear frozen.
        scaled = max(base * factor, 10.0**-self.decimals())
        self.setSingleStep(scaled)
        try:
            super().stepBy(steps)
        finally:
            self.setSingleStep(base)


class AopsSpinBox(QSpinBox):
    """Integer spin box with the same wheel and step-scaling behaviour."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)

    def stepBy(self, steps: int) -> None:
        factor = _step_factor()
        if factor == 1.0:
            super().stepBy(steps)
            return
        base = self.singleStep()
        scaled = max(1, int(round(base * factor)))
        self.setSingleStep(scaled)
        try:
            super().stepBy(steps)
        finally:
            self.setSingleStep(base)


class FieldRow(QFrame):
    """A label, an editor, and an optional unit suffix."""

    def __init__(
        self,
        label: str,
        editor: QWidget,
        path: str,
        *,
        suffix: str = "",
        tooltip: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("fieldRow", True)
        self.path = path
        self.editor = editor
        self._base_tooltip = tooltip

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 0, 2)
        layout.setSpacing(6)

        self.label = QLabel(label, self)
        self.label.setProperty("fieldLabel", True)
        self.label.setMinimumWidth(LABEL_WIDTH)
        self.label.setMaximumWidth(LABEL_WIDTH)
        self.label.setWordWrap(True)

        layout.addWidget(self.label)
        layout.addWidget(editor, 1)

        if suffix:
            unit = QLabel(suffix, self)
            unit.setProperty("fieldLabel", True)
            unit.setMinimumWidth(24)
            layout.addWidget(unit)

        if tooltip:
            self.setToolTip(tooltip)
            editor.setToolTip(tooltip)

        # Everything the filter box searches, lowercased once at build time.
        self._haystack = " ".join((label, suffix, tooltip, path)).lower()

    def matches(self, needle: str) -> bool:
        """True when this row should survive the filter."""
        return not needle or needle in self._haystack

    def apply_findings(self, findings: Iterable[Finding]) -> None:
        """Colour the row and show the message, or clear it."""
        worst: Finding | None = None
        for finding in findings:
            if worst is None or finding.severity > worst.severity:
                worst = finding

        if worst is None or worst.severity < Severity.INFO:
            self.setProperty("severity", "")
            self.setToolTip(self._base_tooltip)
            self.editor.setToolTip(self._base_tooltip)
        else:
            self.setProperty("severity", worst.severity.name)
            text = f"[{worst.rule_id}] {worst.message}"
            if worst.hint:
                text += f"\n\n-> {worst.hint}"
            self.setToolTip(text)
            self.editor.setToolTip(text)

        # Dynamic properties only affect rendering after a style refresh.
        self.style().unpolish(self)
        self.style().polish(self)


def make_double(
    value: float,
    *,
    minimum: float = 0.0,
    maximum: float = 100000.0,
    step: float = 0.5,
    decimals: int = 3,
) -> QDoubleSpinBox:
    box = AopsDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    # Suppress per-keystroke valueChanged - see module docstring.
    box.setKeyboardTracking(False)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    # StrongFocus rather than the default WheelFocus: the wheel must not be able
    # to give a box focus, or scrolling the panel would arm the next scroll to
    # edit it.
    box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return box


def make_int(
    value: int, *, minimum: int = 0, maximum: int = 1_000_000, step: int = 1
) -> QSpinBox:
    box = AopsSpinBox()
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setValue(value)
    box.setKeyboardTracking(False)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return box


#: Attribute holding the Python-side value list for a combo box.
COMBO_VALUES = "_aops_values"


class AopsComboBox(QComboBox):
    """Combo box that ignores the wheel unless focused.

    Same reasoning as the spin boxes, with a sharper edge: a stray wheel notch
    over the substrate combo silently swaps polyester for paper, and over the
    symbology combo it selects a symbology that refuses to export.
    """

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


def make_combo(items: Iterable[tuple[str, Any]], current: Any) -> QComboBox:
    """Build a combo box that preserves the exact Python value of each entry.

    Qt round-trips item data through QVariant, and because every enum in this
    application is a `StrEnum` (a str subclass), that conversion silently
    downgrades members to plain strings. Writing one of those back into the
    frozen config would replace a typed enum with a bare string, and the first
    `.display_name` access downstream would fail.

    So the values are kept on the Python side and indexed positionally.
    """
    combo = AopsComboBox()
    values: list[Any] = []
    for text, data in items:
        combo.addItem(text)
        values.append(data)
    setattr(combo, COMBO_VALUES, values)

    if current in values:
        combo.setCurrentIndex(values.index(current))
    combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    return combo


def combo_value(combo: QComboBox) -> Any:
    """Current Python value of a combo built by `make_combo`."""
    values = getattr(combo, COMBO_VALUES, None)
    index = combo.currentIndex()
    if values is not None and 0 <= index < len(values):
        return values[index]
    return combo.currentData()


def make_check(label: str, checked: bool) -> QCheckBox:
    box = QCheckBox(label)
    box.setChecked(checked)
    return box


def make_line(value: str, placeholder: str = "") -> QLineEdit:
    edit = QLineEdit(value)
    if placeholder:
        edit.setPlaceholderText(placeholder)
    return edit


def make_readonly(value: str) -> QLineEdit:
    edit = QLineEdit(value)
    edit.setReadOnly(True)
    edit.setAlignment(Qt.AlignmentFlag.AlignRight)
    return edit


def make_text(value: str, rows: int = 3) -> QPlainTextEdit:
    edit = QPlainTextEdit(value)
    edit.setFixedHeight(rows * 18)
    return edit


class ReadoutRow(QWidget):
    """A non-editable label/value pair used in the summary panels.

    These carry the densest jargon in the application - "field of view",
    "occlusion tolerance", "butt-splice error" - and until they carried
    tooltips a reader had no way in other than asking someone.
    """

    def __init__(
        self,
        label: str,
        value: str = "-",
        parent: QWidget | None = None,
        *,
        tooltip: str = "",
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(8)

        self._label = QLabel(label, self)
        self._label.setProperty("fieldLabel", True)
        self._label.setMinimumWidth(150)
        self._label.setMaximumWidth(150)
        self._label.setWordWrap(True)

        self._value = QLabel(value, self)
        self._value.setProperty("mono", True)
        self._value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._value.setWordWrap(True)

        layout.addWidget(self._label)
        layout.addWidget(self._value, 1)

        if tooltip:
            # On the row, the label and the value alike: hovering anywhere on
            # the line should explain it, not just the words on the left.
            for widget in (self, self._label, self._value):
                widget.setToolTip(tooltip)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_colour(self, colour: str | None) -> None:
        self._value.setStyleSheet(f"color: {colour};" if colour else "")


class SummaryGroup(QWidget):
    """A titled block of `ReadoutRow`s."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 8)
        self._layout.setSpacing(0)

        heading = QLabel(title.upper(), self)
        heading.setProperty("heading", True)
        self._layout.addWidget(heading)

        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #33383f;")
        self._layout.addWidget(line)

        self._rows: dict[str, ReadoutRow] = {}

    def add(self, key: str, label: str, tooltip: str = "") -> ReadoutRow:
        row = ReadoutRow(label, parent=self, tooltip=tooltip)
        self._rows[key] = row
        self._layout.addWidget(row)
        return row

    def set(self, key: str, value: str, colour: str | None = None) -> None:
        row = self._rows.get(key)
        if row is not None:
            row.set_value(value)
            row.set_colour(colour)


def connect_editor(editor: QWidget, callback: Callable[[Any], None]) -> None:
    """Wire whichever change signal the editor type provides."""
    if isinstance(editor, QDoubleSpinBox | QSpinBox):
        editor.valueChanged.connect(callback)
    elif isinstance(editor, QComboBox):
        editor.currentIndexChanged.connect(lambda _i: callback(combo_value(editor)))
    elif isinstance(editor, QCheckBox):
        editor.toggled.connect(callback)
    elif isinstance(editor, QLineEdit):
        editor.textChanged.connect(callback)
    elif isinstance(editor, QPlainTextEdit):
        editor.textChanged.connect(lambda: callback(editor.toPlainText()))
