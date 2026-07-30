"""The validation issues list and the status-bar severity pill."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aops.core.enums import Severity
from aops.core.validation import Finding, ValidationReport
from aops.ui.theme.palette import OK, SEVERITY_COLOURS


class _IssueRow(QWidget):
    """One finding, with a button that applies its correction.

    The geometry constrains itself in several directions at once, so raising
    the symbol size routinely makes the pitch illegal. Telling the user "raise
    the pitch to at least 32.000 mm" is already better than "invalid geometry",
    but they still have to find the box and type it. This does it.
    """

    fixRequested = Signal(object)  # Fix

    def __init__(self, finding: Finding, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(8)

        text = f"[{finding.rule_id}] {finding.severity.label.upper()}  {finding.message}"
        if finding.hint:
            text += f"\n     -> {finding.hint}"

        label = QLabel(text, self)
        label.setWordWrap(True)
        colour = SEVERITY_COLOURS.get(finding.severity.name)
        if colour and finding.severity >= Severity.WARNING:
            label.setStyleSheet(f"color: {colour};")
        layout.addWidget(label, 1)

        if finding.fix is not None:
            button = QPushButton(finding.fix.label, self)
            button.setToolTip(
                f"Applies immediately and can be undone with Ctrl+Z.\n"
                f"Sets {finding.fix.field} to {finding.fix.value}."
            )
            fix = finding.fix
            button.clicked.connect(lambda: self.fixRequested.emit(fix))
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)


class IssuesPanel(QListWidget):
    """All findings, worst first. Double-click focuses the offending field."""

    findingActivated = Signal(str)  # dotted config path
    fixRequested = Signal(object)  # Fix

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setWordWrap(True)
        self.itemDoubleClicked.connect(self._on_activated)

    def set_report(self, report: ValidationReport) -> None:
        self.clear()
        if not report.findings:
            item = QListWidgetItem("Configuration valid - no issues.")
            item.setForeground(Qt.GlobalColor.gray)
            self.addItem(item)
            return

        for finding in report.sorted():
            item = QListWidgetItem()
            if finding.field:
                item.setData(Qt.ItemDataRole.UserRole, finding.field)
            row = _IssueRow(finding, self)
            row.fixRequested.connect(self.fixRequested.emit)
            item.setSizeHint(row.sizeHint())
            self.addItem(item)
            self.setItemWidget(item, row)

    def _on_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.findingActivated.emit(str(path))


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


class IssuesBox(QFrame):
    """The issues list with a heading that states the count, never behind a tab.

    Issues used to be the third tab of three, which meant the single most
    important thing the application had to say - "the export is blocked, and
    here is the reason" - was two clicks away and invisible by default. The
    status bar carried a pill, but a pill saying "BLOCKED 2 error(s)" without
    the errors is only slightly better than nothing.

    So the list is always on screen. It sits in a splitter, so a user who wants
    a taller preview can shrink it to just the heading - and the heading alone
    still carries the count and the colour, which is the part that must not be
    losable.
    """

    findingActivated = Signal(str)
    fixRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.heading = QLabel("ISSUES", self)
        self.heading.setProperty("heading", True)
        self.heading.setToolTip(
            "Everything the validator found, worst first.\n\n"
            "Double-click a line to jump to the setting that caused it; where a\n"
            "correction is obvious there is a button that applies it, and\n"
            "Ctrl+Z undoes that like any other edit."
        )
        layout.addWidget(self.heading)

        self.list = IssuesPanel(self)
        self.list.setMinimumHeight(60)
        self.list.findingActivated.connect(self.findingActivated.emit)
        self.list.fixRequested.connect(self.fixRequested.emit)
        layout.addWidget(self.list, 1)

    def set_report(self, report: ValidationReport) -> None:
        self.list.set_report(report)

        counts = report.counts()
        errors = counts[Severity.ERROR] + counts[Severity.FATAL]
        warnings = counts[Severity.WARNING]
        notes = counts[Severity.INFO]

        if errors:
            text = f"ISSUES    {errors} blocking"
            if warnings:
                text += f", {_plural(warnings, 'warning')}"
            colour = SEVERITY_COLOURS.get(
                "FATAL" if counts[Severity.FATAL] else "ERROR"
            )
        elif warnings:
            text = f"ISSUES    {_plural(warnings, 'warning')}"
            colour = SEVERITY_COLOURS.get("WARNING")
        elif notes:
            # Not "none". The list below has lines in it, and a green heading
            # saying nothing is wrong directly above them reads as a bug in the
            # application rather than as a distinction between severities.
            text, colour = f"ISSUES    {_plural(notes, 'note')}, none blocking", None
        else:
            text, colour = "ISSUES    none", OK

        self.heading.setText(text)
        self.heading.setStyleSheet(f"color: {colour};" if colour else "")


class StatusPill(QLabel):
    """Compact severity indicator for the status bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("statusPill", True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_report(ValidationReport())

    def set_report(self, report: ValidationReport) -> None:
        counts = report.counts()
        errors = counts[Severity.ERROR] + counts[Severity.FATAL]
        warnings = counts[Severity.WARNING]

        if errors:
            severity, text = "ERROR", f"BLOCKED  {errors} error(s)"
            if counts[Severity.FATAL]:
                severity = "FATAL"
        elif warnings:
            severity, text = "WARNING", f"VALID  {warnings} warning(s)"
        else:
            severity, text = "OK", "CONFIGURATION VALID"

        self.setText(text)
        self.setProperty("severity", severity)
        self.style().unpolish(self)
        self.style().polish(self)
