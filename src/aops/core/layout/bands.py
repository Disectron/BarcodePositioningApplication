"""Vertical band stacking for a printed page.

A strip page is a vertical stack: header, then optionally a ruler, the strip
band itself, the human-readable row, a calibration bar, and a footer. Solving
the stack in one place means the elements cannot overlap, and the total height
is available to validation before anything is drawn.
"""

from __future__ import annotations

from dataclasses import dataclass

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
