"""Modal progress dialog for a running export."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ExportProgressDialog(QDialog):
    """Determinate progress with a working Cancel button."""

    cancelRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exporting")
        self.setModal(True)
        self.setFixedWidth(420)
        # No close button: cancellation must go through the worker so the
        # partial file is cleaned up.
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.phase = QLabel("Preparing...", self)
        layout.addWidget(self.phase)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, 100)
        layout.addWidget(self.bar)

        self.detail = QLabel("", self)
        self.detail.setProperty("sectionCaption", True)
        layout.addWidget(self.detail)

        self.cancel = QPushButton("Cancel", self)
        self.cancel.clicked.connect(self._on_cancel)
        layout.addWidget(self.cancel, alignment=Qt.AlignmentFlag.AlignRight)

    _PHASES = {
        "encoding": "Encoding symbols",
        "drawing": "Drawing pages",
        "verifying": "Verifying symbols decode",
    }

    def set_progress(self, done: int, total: int, phase: str) -> None:
        self.phase.setText(self._PHASES.get(phase, phase.capitalize()))
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            self.detail.setText(f"{done} of {total}")

    def _on_cancel(self) -> None:
        self.cancel.setEnabled(False)
        self.cancel.setText("Cancelling...")
        self.cancelRequested.emit()
