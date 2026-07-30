"""Collapsible accordion sections for the configuration panel.

Each header carries a severity badge. Without it, collapsing a section could
hide an error, and the user would see an export button that refuses to work with
no visible reason.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from aops.core.enums import Severity
from aops.resources.field_levels import UiLevel
from aops.resources.glossary import SECTION_TERMS
from aops.ui.theme.palette import SEVERITY_COLOURS
from aops.ui.widgets.field_row import STEP_HINT


class AccordionSection(QWidget):
    """One numbered, collapsible section."""

    toggled = Signal(bool)

    def __init__(self, number: int, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._number = number

        self.header = QToolButton(self)
        self.header.setProperty("accordionHeader", True)
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.setArrowType(Qt.ArrowType.DownArrow)
        self.header.setText(f"{number}.  {title.upper()}")
        self.header.clicked.connect(self._on_clicked)

        self.badge = QLabel(self.header)
        self.badge.setVisible(False)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.body = QFrame(self)
        self.body.setProperty("accordionBody", True)
        self._body_layout = QVBoxLayout(self.body)
        self._body_layout.setContentsMargins(10, 8, 10, 10)
        self._body_layout.setSpacing(4)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.body)

    def content_layout(self) -> QVBoxLayout:
        return self._body_layout

    def add_widget(self, widget: QWidget) -> None:
        self._body_layout.addWidget(widget)

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)
        self._apply(expanded)

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def _on_clicked(self) -> None:
        self._apply(self.header.isChecked())
        self.toggled.emit(self.header.isChecked())

    def _apply(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.header.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def set_severity(self, severity: Severity | None, count: int = 0) -> None:
        """Show a coloured badge in the header, so a collapsed section can't hide an error.

        The clear path has to reset the style sheet as well as the text. Setting
        only the text left a header that had once carried a warning coloured for
        the rest of the session, long after the warning was resolved - so the
        panel accumulated false alarms as you worked.
        """
        if severity is None or severity < Severity.WARNING:
            self.header.setText(self._plain_title)
            self.header.setStyleSheet("")
            return
        colour = SEVERITY_COLOURS.get(severity.name, "#e0a44a")
        marker = "!" if severity >= Severity.ERROR else "*"
        self.header.setText(f"{self._plain_title}    {marker} {count}")
        self.header.setStyleSheet(f"QToolButton {{ color: {colour}; }}")

    @property
    def _plain_title(self) -> str:
        return f"{self._number}.  {self._title.upper()}"

    def set_visible_for_filter(self, visible: bool) -> None:
        """Hide the whole section when a filter matched nothing inside it."""
        self.setVisible(visible)


class AccordionPanel(QWidget):
    """Vertical stack of accordion sections, with a filter box above them."""

    filterChanged = Signal(str)
    modeChanged = Signal(object)  # UiLevel

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(0)
        self._sections: dict[str, AccordionSection] = {}
        self._counter = 0

        self._layout.addWidget(self._build_toolbar())

    def _build_toolbar(self) -> QWidget:
        """Filter box plus expand/collapse, above the sections.

        With eleven sections and sixty-odd fields, "which box was the quiet
        zone in?" is a real question. Typing 'quiet' answers it without the
        user needing to know which section owns the field.
        """
        bar = QWidget(self)
        row = QVBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 6)
        row.setSpacing(4)

        modes = QHBoxLayout()
        modes.setSpacing(4)
        self.mode_buttons: dict[UiLevel, QToolButton] = {}
        for level in (UiLevel.SIMPLE, UiLevel.ADVANCED):
            button = QToolButton(bar)
            button.setText(level.display_name)
            button.setCheckable(True)
            button.setToolTip(level.description)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _c=False, m=level: self.modeChanged.emit(m))
            self.mode_buttons[level] = button
            modes.addWidget(button)
        row.addLayout(modes)

        self.mode_note = QLabel("", bar)
        self.mode_note.setProperty("sectionCaption", True)
        self.mode_note.setWordWrap(True)
        row.addWidget(self.mode_note)

        top = QHBoxLayout()
        top.setSpacing(4)

        self.filter_edit = QLineEdit(bar)
        self.filter_edit.setPlaceholderText("Filter settings...   (Ctrl+F)")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.filterChanged.emit)
        top.addWidget(self.filter_edit, 1)

        self.expand_button = QToolButton(bar)
        self.expand_button.setText("Expand all")
        self.expand_button.clicked.connect(lambda: self.set_all_expanded(True))
        top.addWidget(self.expand_button)

        self.collapse_button = QToolButton(bar)
        self.collapse_button.setText("Collapse all")
        self.collapse_button.clicked.connect(lambda: self.set_all_expanded(False))
        top.addWidget(self.collapse_button)

        row.addLayout(top)

        hint = QLabel(STEP_HINT, bar)
        hint.setProperty("sectionCaption", True)
        row.addWidget(hint)

        return bar

    def add_section(self, key: str, title: str) -> AccordionSection:
        self._counter += 1
        section = AccordionSection(self._counter, title, self)
        tooltip = SECTION_TERMS.get(key, "")
        if tooltip:
            section.header.setToolTip(tooltip)
        self._sections[key] = section
        self._layout.addWidget(section)
        return section

    def finish(self) -> None:
        self._layout.addStretch(1)

    def section(self, key: str) -> AccordionSection | None:
        return self._sections.get(key)

    def sections(self) -> dict[str, AccordionSection]:
        return dict(self._sections)

    def show_mode(self, mode: UiLevel, hidden_count: int) -> None:
        """Reflect the active mode on the toggle and say what it is holding back."""
        for level, button in self.mode_buttons.items():
            button.setChecked(level is mode)
        if mode is UiLevel.SIMPLE:
            self.mode_note.setText(
                f"The settings a typical strip needs. {hidden_count} more in Advanced, "
                f"all keeping a sensible default."
            )
        else:
            self.mode_note.setText("Every setting. Switch to Simple for just the essentials.")

    def flag_hidden_match(self, count: int) -> None:
        """Warn that a filter matched fields the current mode is hiding."""
        if count > 0:
            self.mode_note.setText(
                f"{count} more match in Advanced - switch to see them."
            )

    def set_all_expanded(self, expanded: bool) -> None:
        for section in self._sections.values():
            section.set_expanded(expanded)

    def focus_filter(self) -> None:
        self.filter_edit.setFocus()
        self.filter_edit.selectAll()

    def filter_text(self) -> str:
        return self.filter_edit.text()
