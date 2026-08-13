"""Vertical band stacking for a printed page.

A strip page is a vertical stack: header, then optionally a ruler, the strip
band itself, the human-readable row, a calibration bar, and a footer. Solving
the stack in one place means the elements cannot overlap, and the total height
is available to validation before anything is drawn.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from aops.core.config import AopsConfig
from aops.core.enums import RulerPosition

HEADER_H_MM = 8.0
FOOTER_H_MM = 6.0
RULER_H_MM = 10.0
CALIBRATION_H_MM = 16.0
GAP_MM = 3.0


@dataclass(frozen=True, slots=True)
class BandLayout:
    """Resolved Y offsets (mm, from the top of the content area) for one page."""

    header_baseline_mm: float
    ruler_y_mm: float | None
    strip_top_mm: float
    strip_height_mm: float
    calibration_y_mm: float | None
    footer_baseline_mm: float
    total_height_mm: float

    @property
    def strip_bottom_mm(self) -> float:
        return self.strip_top_mm + self.strip_height_mm


def solve_bands(cfg: AopsConfig, *, with_calibration: bool) -> BandLayout:
    """Stack the page bands top to bottom.

    With the header and footer suppressed their bands are removed rather than
    merely left blank, so a plain print is as short as its content - which is
    what lets it fit media that the full commissioning layout would not.
    """
    furniture = cfg.output.page_header_footer
    y = 0.0

    if furniture:
        y += HEADER_H_MM
        header_baseline = y - 2.4
        y += GAP_MM
    else:
        header_baseline = 0.0

    ruler_y: float | None = None
    if cfg.output.engineering_ruler and cfg.output.ruler_position is RulerPosition.ABOVE:
        ruler_y = y
        y += RULER_H_MM + GAP_MM

    strip_top = y
    strip_h = cfg.dimensions.strip_height_mm
    y += strip_h + GAP_MM

    if cfg.output.engineering_ruler and cfg.output.ruler_position is RulerPosition.BELOW:
        ruler_y = y
        y += RULER_H_MM + GAP_MM

    calibration_y: float | None = None
    if with_calibration:
        calibration_y = y
        y += CALIBRATION_H_MM + GAP_MM

    if furniture:
        footer_baseline = y + FOOTER_H_MM - 2.0
        y += FOOTER_H_MM
    else:
        # Trailing GAP_MM from the last band above is the whole bottom margin.
        footer_baseline = y

    return BandLayout(
        header_baseline_mm=header_baseline,
        ruler_y_mm=ruler_y,
        strip_top_mm=strip_top,
        strip_height_mm=strip_h,
        calibration_y_mm=calibration_y,
        footer_baseline_mm=footer_baseline,
        total_height_mm=y,
    )


# -- multi-row sheets --------------------------------------------------------

#: Caption line above each row ("ROW 3   X 540-810 mm ..."), so a cut-out row
#: still identifies itself after the footer has been trimmed away.
ROW_CAPTION_H_MM = 6.0

#: Cutting zone between rows: the dashed guide line and scissor clearance.
ROW_GAP_MM = 5.0

#: Sanity cap for the auto-fit search. Forty 20 mm rows is more than any
#: supported sheet can hold.
MAX_ROWS = 40


@dataclass(frozen=True, slots=True)
class SheetBandLayout:
    """Resolved Y offsets for a sheet carrying several strip rows.

    `row` is the layout *within* one row block, relative to that row's top -
    the same `BandLayout` a single-row page uses, minus header, footer and
    calibration, which belong to the sheet.
    """

    header_baseline_mm: float
    row_tops_mm: tuple[float, ...]
    row: BandLayout
    cut_line_ys_mm: tuple[float, ...]
    calibration_y_mm: float | None
    footer_baseline_mm: float
    total_height_mm: float


def solve_sheet_bands(
    cfg: AopsConfig, rows: int, *, with_calibration: bool
) -> SheetBandLayout:
    """Stack `rows` strip rows plus the sheet furniture, top to bottom.

    Header, footer and the calibration bar appear once per sheet; each row
    block is a caption line plus the row's own band stack (strip, ruler if
    enabled). Between rows sits the cutting zone.
    """
    row_cfg = replace(cfg, output=replace(cfg.output, page_header_footer=False))
    row = solve_bands(row_cfg, with_calibration=False)

    furniture = cfg.output.page_header_footer
    y = 0.0
    header_baseline = 0.0
    if furniture:
        y += HEADER_H_MM
        header_baseline = y - 2.4
        y += GAP_MM

    row_tops: list[float] = []
    cut_ys: list[float] = []
    for i in range(max(1, rows)):
        y += ROW_CAPTION_H_MM
        row_tops.append(y)
        y += row.total_height_mm
        if i < rows - 1:
            cut_ys.append(y + ROW_GAP_MM / 2.0)
            y += ROW_GAP_MM

    calibration_y: float | None = None
    if with_calibration:
        calibration_y = y
        y += CALIBRATION_H_MM + GAP_MM

    if furniture:
        footer_baseline = y + FOOTER_H_MM - 2.0
        y += FOOTER_H_MM
    else:
        footer_baseline = y

    return SheetBandLayout(
        header_baseline_mm=header_baseline,
        row_tops_mm=tuple(row_tops),
        row=row,
        cut_line_ys_mm=tuple(cut_ys),
        calibration_y_mm=calibration_y,
        footer_baseline_mm=footer_baseline,
        total_height_mm=y,
    )


def rows_that_fit(cfg: AopsConfig, *, with_calibration: bool) -> int:
    """Most rows the sheet's usable height carries. Never below one.

    Computed against the calibration-bearing sheet so every sheet of a job
    gets the same row count - a run where sheet one holds five rows and the
    rest hold six would make "which sheet is row 23 on" a division nobody
    should have to do. The drawn height scales with the printer correction,
    so capacity is measured in corrected millimetres.
    """
    usable = cfg.paper.usable_height_mm() / max(cfg.printing.scale_factor, 1e-9)
    for rows in range(MAX_ROWS, 1, -1):
        if solve_sheet_bands(cfg, rows, with_calibration=with_calibration).total_height_mm <= usable:
            return rows
    return 1
