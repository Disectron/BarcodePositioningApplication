"""The question the auto-fixer asks when two rules fight over one field.

An over-constrained strip has no computable answer - the reader's window
wants the code spacing smaller, the cutting tolerance wants it bigger, and
whichever the fixer picked it would be silently overruling the other. The
user has said, in as many words, that they want to be asked. This dialog is
that question, put with everything needed to answer it: what each side wants,
how bad each side's complaint is, and what choosing each way costs.

The third way out is always offered too: neither value, but a different job.
Most fights dissolve if the reader moves back, the redundancy drops, or the
code shrinks - and Design strip derives exactly such a geometry. A dialog
that only offered the two fighting values would railroad the user into a
compromise when the better answer is to remove the fight.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aops.core.autofix import Conflict
from aops.core.enums import Severity


def _side_text(rule: str, severity: Severity, value: object) -> str:
    label = severity.label.upper() if rule != "your setting" else "yours"
    return f"{value}  -  [{rule}] ({label})"


class ConflictDialog(QDialog):
    """Present one fight and collect the user's ruling.

    Exposes the choice as `choice`: "challenger", "incumbent" or None (the
    user closed the dialog or chose to adjust the job instead). Built so tests
    can construct it, read its labels and click its buttons without exec().
    """

    def __init__(self, conflict: Conflict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Two settings are fighting")
        self.conflict = conflict
        self.choice: str | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QLabel(
            f"The auto-fixer cannot settle <b>{conflict.field}</b> - two rules "
            f"pull it in opposite directions, and choosing is a judgement call:",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        challenger_text = QLabel(
            f"<b>[{conflict.challenger_rule}]</b> "
            f"({conflict.challenger_severity.label})<br>"
            f"{conflict.challenger_message}",
            self,
        )
        challenger_text.setWordWrap(True)
        layout.addWidget(challenger_text)

        if conflict.incumbent_message:
            incumbent_text = QLabel(
                f"<b>[{conflict.incumbent_rule}]</b> "
                f"({conflict.incumbent_severity.label}) - if you take "
                f"{conflict.challenger_value}:<br>{conflict.incumbent_message}",
                self,
            )
            incumbent_text.setWordWrap(True)
            layout.addWidget(incumbent_text)

        # Each button says what taking it costs, not just what it sets. The
        # severity labels are the heart of the decision: one side is usually
        # an error and the other a warning, and the user should see that.
        self.challenger_button = QPushButton(
            f"Use {conflict.challenger_value}  -  satisfies "
            f"[{conflict.challenger_rule}], accepts what "
            f"[{conflict.incumbent_rule}] warns about",
            self,
        )
        self.challenger_button.clicked.connect(lambda: self._choose("challenger"))
        layout.addWidget(self.challenger_button)

        self.incumbent_button = QPushButton(
            f"Keep {conflict.incumbent_value}  -  as "
            f"[{conflict.incumbent_rule}] set it, leaves "
            f"[{conflict.challenger_rule}] standing",
            self,
        )
        self.incumbent_button.clicked.connect(lambda: self._choose("incumbent"))
        layout.addWidget(self.incumbent_button)

        self.job_button = QPushButton(
            "Neither - I will change the job (mounting distance, codes in "
            "view, code size), or press Design strip",
            self,
        )
        self.job_button.clicked.connect(self.reject)
        layout.addWidget(self.job_button)

        note = QLabel(
            "Whichever you choose applies as one edit and Ctrl+Z undoes it.",
            self,
        )
        note.setProperty("sectionCaption", True)
        note.setWordWrap(True)
        layout.addWidget(note)

    def _choose(self, side: str) -> None:
        self.choice = side
        self.accept()
