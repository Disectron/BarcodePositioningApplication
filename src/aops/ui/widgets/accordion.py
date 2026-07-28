"""Collapsible accordion sections for the configuration panel.

Each header carries a severity badge. Without it, collapsing a section could
hide an error, and the user would see an export button that refuses to work with
no visible reason.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from aops.core.enums import Severity
from aops.ui.theme.palette import SEVERITY_COLOURS


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

    def _on_clicked(self) -> None:
        self._apply(self.header.isChecked())
        self.toggled.emit(self.header.isChecked())

    def _apply(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.header.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def set_severity(self, severity: Severity | None, count: int = 0) -> None:
        """Show a coloured badge in the header, so a collapsed section can't hide an error."""
        if severity is None or severity < Severity.WARNING:
            self.header.setText(f"{self._number}.  {self._title.upper()}")
            return
        colour = SEVERITY_COLOURS.get(severity.name, "#e0a44a")
        marker = "!" if severity >= Severity.ERROR else "*"
        self.header.setText(f"{self._number}.  {self._title.upper()}    {marker} {count}")
        self.header.setStyleSheet(f"QToolButton {{ color: {colour}; }}")
        if severity < Severity.WARNING:
            self.header.setStyleSheet("")


class AccordionPanel(QWidget):
    """Vertical stack of accordion sections."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(0)
        self._sections: dict[str, AccordionSection] = {}
        self._counter = 0

    def add_section(self, key: str, title: str) -> AccordionSection:
        self._counter += 1
        section = AccordionSection(self._counter, title, self)
        self._sections[key] = section
        self._layout.addWidget(section)
        return section

    def finish(self) -> None:
        self._layout.addStretch(1)

    def section(self, key: str) -> AccordionSection | None:
        return self._sections.get(key)

    def sections(self) -> dict[str, AccordionSection]:
        return dict(self._sections)
