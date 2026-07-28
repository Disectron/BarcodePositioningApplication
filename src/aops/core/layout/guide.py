"""The auto-generated installation guide.

Page 1 (and, if needed, page 2) of every tiled export. It is generated from the
same `DerivedGeometry` that produced the strip, so it can never describe a
different strip from the one printed behind it - including the position formula,
which is what the controls engineer types into the PLC.

The guide **flows onto additional pages rather than truncating**. Silently
dropping the Verification and Warnings sections off the bottom of a page would
be the worst kind of bug here: the document would look complete while omitting
the safety content.
"""

from __future__ import annotations

from aops.core.config import AopsConfig
from aops.core.drawlist import DrawList, Line, Primitive, Text, TextStyle
from aops.core.layout import style as S
from aops.core.stats import DerivedGeometry
from aops.core.text_metrics import DEFAULT_METRICS, TextMeasurer
from aops.resources.guide_text import (
    CALIBRATION_STEPS,
    PRINT_CHECKLIST,
    VERIFICATION_STEPS,
    media_notes,
    mounting_steps,
    scanner_notes,
    warnings,
)

_LINE_MM = 3.7
_HEADING_GAP_MM = 2.4
_COLUMN_GAP_MM = 8.0
_TITLE_H_MM = 11.0


class _Flow:
    """Two-column text flow that starts a new page instead of overflowing."""

    def __init__(
        self, width_mm: float, height_mm: float, top_mm: float, measurer: TextMeasurer
    ) -> None:
        self.width = width_mm
        self.height = height_mm
        self.top = top_mm
        self.col_w = (width_mm - _COLUMN_GAP_MM) / 2.0
        self.measurer = measurer
        self.pages: list[list[Primitive]] = [[]]
        self._column = 0
        self.x = 0.0
        self.y = top_mm

    # -- page/column management --------------------------------------------

    def _advance(self, needed_mm: float) -> None:
        if self.y + needed_mm <= self.height:
            return
        if self._column == 0:
            self._column = 1
            self.x = self.col_w + _COLUMN_GAP_MM
            self.y = self.top
        else:
            self.pages.append([])
            self._column = 0
            self.x = 0.0
            # Continuation pages have no title band, so they start higher.
            self.top = 6.0
            self.y = self.top

    @property
    def _items(self) -> list[Primitive]:
        return self.pages[-1]

    # -- content -----------------------------------------------------------

    def heading(self, text: str) -> None:
        self._advance(_LINE_MM * 3)
        self.y += _HEADING_GAP_MM
        self._items.append(Text(self.x, self.y, text.upper(), S.GUIDE_HEADING))
        self.y += 1.1
        self._items.append(Line(self.x, self.y, self.x + self.col_w, self.y, S.RULE_LINE))
        self.y += _LINE_MM

    def body(self, text: str, style: TextStyle = S.GUIDE_BODY) -> None:
        for line in self._wrap(text, style, self.col_w):
            self._advance(_LINE_MM)
            self._items.append(Text(self.x, self.y, line, style))
            self.y += _LINE_MM

    def bullet(self, text: str, marker: str = "-", style: TextStyle = S.GUIDE_BODY) -> None:
        indent = self.measurer.width_mm(f"{marker} ", style.role, style.size_pt)
        lines = self._wrap(text, style, self.col_w - indent)
        for i, line in enumerate(lines):
            self._advance(_LINE_MM)
            prefix = f"{marker} " if i == 0 else ""
            x = self.x if i == 0 else self.x + indent
            self._items.append(Text(x, self.y, f"{prefix}{line}", style))
            self.y += _LINE_MM

    def field(self, label: str, value: str) -> None:
        self._advance(_LINE_MM)
        self._items.append(Text(self.x, self.y, f"{label:<20}{value}", S.GUIDE_MONO))
        self.y += _LINE_MM

    def mono(self, text: str) -> None:
        self._advance(_LINE_MM)
        self._items.append(Text(self.x, self.y, text, S.GUIDE_MONO))
        self.y += _LINE_MM

    def gap(self, mm: float = 1.5) -> None:
        self.y += mm

    def _wrap(self, text: str, style: TextStyle, width_mm: float) -> list[str]:
        words = text.split()
        if not words:
            return [""]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if self.measurer.width_mm(trial, style.role, style.size_pt) <= width_mm:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines


def compose_guide_pages(
    cfg: AopsConfig,
    derived: DerivedGeometry,
    fingerprint: str,
    timestamp: str,
    *,
    measurer: TextMeasurer | None = None,
) -> tuple[DrawList, ...]:
    """Build the installation guide, flowing onto extra pages if required."""
    measurer = measurer or DEFAULT_METRICS
    width = cfg.paper.usable_width_mm()
    height = cfg.paper.usable_height_mm()

    flow = _Flow(width, height, _TITLE_H_MM + 3.0, measurer)
    p, cell, acc = cfg.project, derived.cell, derived.accuracy

    flow.heading("Identification")
    flow.field("Machine", p.machine or "-")
    flow.field("Project", p.project or "-")
    flow.field("Strip ID", p.strip_id or "-")
    flow.field("Revision", p.revision or "-")
    flow.field("Engineer", p.engineer or "-")
    flow.field("Company", p.company or "-")
    flow.field("Generated", timestamp)
    flow.field("Fingerprint", fingerprint)
    if p.comments:
        flow.gap()
        flow.body(p.comments[:400])

    flow.heading("Strip specification")
    flow.field("Symbology", cfg.symbol.symbology.display_name)
    flow.field("Cell pitch", f"{cell.pitch_mm:.3f} mm")
    flow.field("Symbol size", f"{cell.symbol_mm:.3f} mm")
    flow.field("Module size", f"{derived.scanner.module_size_mm:.4f} mm")
    flow.field("Quiet zone", f"{cell.quiet_zone_mm:.3f} mm")
    flow.field("Margin L/R", f"{cell.margin_lr_mm:.3f} mm")
    flow.field("Strip height", f"{cell.strip_height_mm:.3f} mm")
    flow.field("Codes", str(derived.code_count))
    flow.field("Total length", f"{derived.total_length_mm:.1f} mm ({derived.total_length_mm / 1000:.3f} m)")
    flow.field("Max position", f"{derived.max_position_mm:.1f} mm")
    flow.field("Per code", f"{derived.distance_per_code_mm:.3f} mm")
    flow.field("Sheets", str(len(derived.pages)))

    flow.heading("Position formula")
    flow.body(
        "Program the PLC with exactly this expression. It is generated from the same "
        "geometry that produced the printed strip:"
    )
    flow.gap(0.8)
    flow.mono(derived.position_formula)
    flow.gap(0.8)
    flow.body(
        f"Each symbol encodes its own absolute position in millimetres, zero padded to "
        f"{cfg.payload.digits} digits. The human-readable text below each symbol is the "
        f"same string the reader decodes."
    )

    flow.heading("Printing")
    for line in PRINT_CHECKLIST:
        flow.bullet(line)
    flow.gap()
    flow.field("Resolution", f"{cfg.printer.dpi} dpi")
    flow.field("Scaling", f"{cfg.printing.scale_percent:.3f} %")
    flow.field("Paper", f"{cfg.paper.preset.value} {cfg.paper.orientation.value}")
    flow.field("Module dots", f"{acc.module_dots:.1f} (>= 3 required, >= 5 preferred)")

    flow.heading("Calibration")
    for i, line in enumerate(CALIBRATION_STEPS, 1):
        flow.bullet(line, f"{i}.")
    flow.gap(0.8)
    flow.body(
        f"THE CALIBRATION BAR MUST MEASURE EXACTLY "
        f"{cfg.printing.calibration_length_mm:.0f} mm.",
        S.GUIDE_WARNING,
    )

    flow.heading("Media")
    for line in media_notes(cfg, derived):
        flow.bullet(line)

    flow.heading("Installation")
    for i, line in enumerate(mounting_steps(cfg, derived), 1):
        flow.bullet(line, f"{i}.")

    flow.heading("Reader selection and mounting")
    for line in scanner_notes(cfg, derived):
        flow.bullet(line)

    flow.heading("Verification")
    for line in VERIFICATION_STEPS:
        flow.bullet(line)

    flow.heading("Warnings")
    for line in warnings(cfg, derived):
        flow.bullet(line, "!", S.GUIDE_WARNING)

    pages: list[DrawList] = []
    for n, items in enumerate(flow.pages):
        header: list[Primitive] = []
        if n == 0:
            header = [
                Text(0.0, 6.5, "ABSOLUTE OPTICAL POSITION STRIP - INSTALLATION GUIDE", S.GUIDE_TITLE),
                Line(0.0, 9.0, width, 9.0, S.RULE_LINE),
            ]
        else:
            header = [
                Text(0.0, 4.0, f"INSTALLATION GUIDE (CONTINUED {n + 1})", S.GUIDE_HEADING),
                Line(0.0, 5.2, width, 5.2, S.RULE_LINE),
            ]
        pages.append(DrawList(width, height, tuple(header) + tuple(items)))
    return tuple(pages)


def compose_guide_page(
    cfg: AopsConfig,
    derived: DerivedGeometry,
    fingerprint: str,
    timestamp: str,
    *,
    measurer: TextMeasurer | None = None,
) -> DrawList:
    """First guide page only. Retained for callers that want a single sheet."""
    return compose_guide_pages(cfg, derived, fingerprint, timestamp, measurer=measurer)[0]
