"""The job bar: the four numbers that identify a strip, always on screen.

Everything else in this application is a *setting*. These are the job: which
machine the tape is going on, which strip of it this is, and how far the axis
travels. They were previously buried in section 10 and section 2 respectively,
which meant the two identifiers printed on every page were the two hardest
things in the interface to find, and the length of the axis - the one dimension
the engineer measured before opening the software - was not expressible at all.

AXIS TRAVEL RATHER THAN END INDEX
---------------------------------
The strip is built from an index range, but nobody measures a machine in
indices. They measure it in millimetres, and then have to divide by the pitch
to get an end index - which is arithmetic the software can do, and can do
without the off-by-one that catches people (a 2000 mm axis at 25 mm pitch needs
index 80, not 81, because the first code sits at zero).

So the bar asks for travel and derives the index. The box then shows the travel
the range actually achieves, which is rounded up to the next whole code: see
`end_index_for_travel` for why up rather than down. When those two numbers
differ the caption says so, because silently printing 25 mm more tape than
asked for is the kind of surprise that gets found at the machine.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from aops.core.config import AopsConfig
from aops.core.positions import travel_mm
from aops.core.stats import DerivedGeometry
from aops.ui.theme.palette import SEVERITY_COLOURS
from aops.ui.widgets.field_row import AopsDoubleSpinBox

TRAVEL_TOOLTIP = (
    "How far the axis moves, from the first code to the last.\n\n"
    "This is the number you measured on the machine. AOPS turns it into an\n"
    "index range for you. The range always reaches at least this far - it is\n"
    "rounded up to a whole code, because stopping short would leave the end of\n"
    "the axis with no code over it and the machine would lose absolute position\n"
    "exactly where it runs out of travel."
)

MACHINE_TOOLTIP = (
    "Which machine this tape is being made for.\n\n"
    "Printed on every page and on the installation guide. A strip with no\n"
    "machine name on it is indistinguishable from any other strip once it is\n"
    "off the printer."
)

STRIP_TOOLTIP = (
    "Which strip this is, if the machine has more than one axis.\n\n"
    "Printed on every page. 'X-AXIS' and 'Y-AXIS' is enough; the point is that\n"
    "two strips lying on the same bench can be told apart."
)


class JobBar(QFrame):
    """Identity and length of the strip, above everything else."""

    #: (dotted config path, new value) for the two text fields.
    fieldEdited = Signal(str, str)
    #: Axis travel in millimetres, for the window to convert to an end index.
    travelRequested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("jobBar", True)
        self._loading = False
        #: What the user last typed, so the caption can report the rounding
        #: without mistaking a programmatic refresh for a request.
        self._requested_mm: float | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 5, 8, 5)
        outer.setSpacing(2)

        row = QHBoxLayout()
        row.setSpacing(6)

        self.machine_edit = QLineEdit(self)
        self.machine_edit.setPlaceholderText("machine name")
        self.machine_edit.setToolTip(MACHINE_TOOLTIP)
        self.machine_edit.setMinimumWidth(150)
        self.machine_edit.textEdited.connect(
            lambda text: self._emit_field("project.machine", text)
        )

        self.strip_edit = QLineEdit(self)
        self.strip_edit.setPlaceholderText("X-AXIS")
        self.strip_edit.setToolTip(STRIP_TOOLTIP)
        self.strip_edit.setMinimumWidth(110)
        self.strip_edit.textEdited.connect(
            lambda text: self._emit_field("project.strip_id", text)
        )

        self.travel_spin = AopsDoubleSpinBox(self)
        self.travel_spin.setRange(0.0, 1_000_000.0)
        self.travel_spin.setDecimals(1)
        self.travel_spin.setSingleStep(10.0)
        self.travel_spin.setKeyboardTracking(False)
        self.travel_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.travel_spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.travel_spin.setToolTip(TRAVEL_TOOLTIP)
        self.travel_spin.setMinimumWidth(110)
        self.travel_spin.valueChanged.connect(self._on_travel_changed)

        # Sized rather than stretched. Left to share the free space, the machine
        # box grew to half the window - a text field the width of the preview
        # reads as the most important control on screen, which it is not.
        self.machine_edit.setMaximumWidth(260)
        self.strip_edit.setMaximumWidth(170)

        for label, widget in (
            ("Machine", self.machine_edit),
            ("Strip", self.strip_edit),
        ):
            caption = QLabel(label, self)
            caption.setProperty("fieldLabel", True)
            caption.setToolTip(widget.toolTip())
            row.addWidget(caption)
            row.addWidget(widget)

        row.addStretch(1)

        travel_caption = QLabel("Axis travel", self)
        travel_caption.setProperty("fieldLabel", True)
        travel_caption.setToolTip(TRAVEL_TOOLTIP)
        row.addWidget(travel_caption)
        row.addWidget(self.travel_spin)

        unit = QLabel("mm", self)
        unit.setProperty("fieldLabel", True)
        row.addWidget(unit)

        outer.addLayout(row)

        #: Restored when a finding on a bar field is resolved, so the tooltip
        #: goes back to explaining the field rather than staying on a stale
        #: message.
        self._base_tooltips = {
            "project.machine": MACHINE_TOOLTIP,
            "project.strip_id": STRIP_TOOLTIP,
        }

        self.readout = QLabel("", self)
        self.readout.setProperty("mono", True)
        self.readout.setToolTip(
            "What the settings below currently produce. Every one of these is a\n"
            "derived value - change the geometry and they follow."
        )
        outer.addWidget(self.readout)

        self.note = QLabel("", self)
        self.note.setProperty("sectionCaption", True)
        self.note.setWordWrap(True)
        outer.addWidget(self.note)

    # -- findings ------------------------------------------------------------

    def fields(self) -> dict[str, QWidget]:
        """Config paths this bar owns, so a finding can be routed here.

        PRJ-001 ("no strip ID") points at `project.strip_id`, which is no longer
        an accordion row in Simple mode. Without this the window would switch to
        Advanced to reach a box that was on screen the whole time.
        """
        return {
            "project.machine": self.machine_edit,
            "project.strip_id": self.strip_edit,
        }

    def focus_field(self, path: str) -> bool:
        widget = self.fields().get(path)
        if widget is None:
            return False
        widget.setFocus()
        return True

    def apply_validation(self, report) -> None:  # type: ignore[no-untyped-def]
        """Tint a bar field that a finding points at, and explain it on hover."""
        for path, widget in self.fields().items():
            worst = max(
                report.for_field(path), key=lambda f: f.severity, default=None
            )
            if worst is None:
                widget.setStyleSheet("")
                widget.setToolTip(self._base_tooltips[path])
                continue
            colour = SEVERITY_COLOURS.get(worst.severity.name)
            widget.setStyleSheet(
                f"QLineEdit {{ border: 1px solid {colour}; }}" if colour else ""
            )
            text = f"[{worst.rule_id}] {worst.message}"
            if worst.hint:
                text += f"\n\n-> {worst.hint}"
            widget.setToolTip(text)

    # -- editing ------------------------------------------------------------

    def _emit_field(self, path: str, text: str) -> None:
        if not self._loading:
            self.fieldEdited.emit(path, text)

    def _on_travel_changed(self, value: float) -> None:
        if self._loading:
            return
        self._requested_mm = value
        self.travelRequested.emit(value)

    # -- refresh ------------------------------------------------------------

    def update_from(self, cfg: AopsConfig, derived: DerivedGeometry | None) -> None:
        """Mirror the configuration, and report what it produces.

        Guarded like the configuration panels: writing the achieved travel back
        into the spin box emits `valueChanged`, and without the guard that would
        be indistinguishable from the user asking for it - so a value rounded up
        by one code would be re-submitted, rounded up again, and the strip would
        grow by a code on every recompute.
        """
        self._loading = True
        try:
            self._mirror_text(self.machine_edit, cfg.project.machine)
            self._mirror_text(self.strip_edit, cfg.project.strip_id)
            if derived is not None:
                achieved = travel_mm(cfg.position, derived.cell)
                if abs(self.travel_spin.value() - achieved) > 5e-2:
                    self.travel_spin.setValue(achieved)
                self._show(cfg, derived, achieved)
            else:
                self.readout.setText("geometry unresolved")
                self.note.setText(
                    "Fix the blocking issue below and these numbers come back."
                )
        finally:
            self._loading = False

    @staticmethod
    def _mirror_text(edit: QLineEdit, value: str) -> None:
        """Write a value in without moving the caret out from under the user."""
        if edit.text() == value:
            return
        cursor = edit.cursorPosition()
        edit.setText(value)
        edit.setCursorPosition(min(cursor, len(value)))

    def _show(self, cfg: AopsConfig, derived: DerivedGeometry, achieved: float) -> None:
        pos = cfg.position
        sheets = derived.total_pdf_pages
        self.readout.setText(
            f"{derived.code_count} codes   "
            f"index {pos.start_index}-{pos.end_index}   "
            f"{derived.cell.pitch_mm:.3f} mm apart   "
            f"{derived.total_length_mm / 1000:.3f} m of tape   "
            f"{sheets} sheet{'' if sheets == 1 else 's'}"
        )

        # Only remark on the rounding when the user asked for a specific travel
        # and did not get exactly it. Saying it unprompted on every refresh would
        # train people to stop reading the line.
        #
        # The request is consumed here rather than remembered. Held on to, it
        # would be compared against a travel that had since changed for an
        # unrelated reason - raise the pitch after asking for 2010 mm and the
        # note would claim 2010 had been "rounded up" to 2430, which is not what
        # happened.
        asked, self._requested_mm = self._requested_mm, None
        if asked is not None and achieved - asked > 5e-2:
            self.note.setText(
                f"Rounded up from {asked:.1f} mm to {achieved:.1f} mm - the next "
                f"whole code, so the end of the axis stays covered."
            )
        else:
            self.note.setText("")
