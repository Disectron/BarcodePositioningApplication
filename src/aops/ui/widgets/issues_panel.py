"""The validation issues list and the status-bar severity pill."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QWidget

from aops.core.enums import Severity
from aops.core.validation import Finding, ValidationReport
from aops.ui.theme.palette import SEVERITY_COLOURS


class IssuesPanel(QListWidget):
    """All findings, worst first. Double-click focuses the offending field."""

    findingActivated = Signal(str)  # dotted config path

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
            self.addItem(self._make_item(finding))

    def _make_item(self, finding: Finding) -> QListWidgetItem:
        text = f"[{finding.rule_id}] {finding.severity.label.upper()}  {finding.message}"
        if finding.hint:
            text += f"\n      -> {finding.hint}"
        item = QListWidgetItem(text)
        colour = SEVERITY_COLOURS.get(finding.severity.name)
        if colour and finding.severity >= Severity.WARNING:
            item.setForeground(Qt.GlobalColor.white)
            from PySide6.QtGui import QColor

            item.setForeground(QColor(colour))
        if finding.field:
            item.setData(Qt.ItemDataRole.UserRole, finding.field)
        return item

    def _on_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.findingActivated.emit(str(path))


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
