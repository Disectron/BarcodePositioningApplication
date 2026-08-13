"""`DerivedGeometry` - everything computable from a configuration.

This is the single object the whole application reads from. The controller
computes it once per configuration change and hands the same instance to the
preview, the summary panels, the validation rules and the exporters, which is
what stops any two of them disagreeing about how long the strip is.

It is a pure function of `AopsConfig`, contains no Qt or ReportLab types, and is
cheap enough to recompute on every keystroke (~200 us for a 421-code strip).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from aops.core.cell import CellSpec, resolve_cell
from aops.core.config import AopsConfig
from aops.core.enums import ContinuousStrategy, PitchMode
from aops.core.errors import GeometryError
from aops.core.geometry import (
    PageLayout,
    Segment,
    build_segments,
    cells_per_page,
    paginate,
    total_strip_length_um,
    usable_width_um,
)
from aops.core.layout.bands import rows_that_fit
from aops.core.media import AccuracyReport, accuracy_report
from aops.core.payload import all_payloads, precision_loss_mm, required_digits
from aops.core.positions import (
    code_count,
    distance_per_code_mm,
    max_position_mm,
    position_formula,
    strip_length_mm,
)
from aops.core.scanner import ScannerRecommendation, recommend
from aops.core.units import PDF_MAX_PT, mm_to_pt, um_to_mm


@dataclass(frozen=True, slots=True)
class ContinuousSpec:
    """Page sizing for the single-page continuous export."""

    width_mm: float
    height_mm: float
    width_pt: float
    height_pt: float
    user_unit: float
    over_limit: bool
    roll_count: int
    roll_length_mm: float
    strategy: ContinuousStrategy


def user_unit_for(width_pt: float, height_pt: float) -> float:
    """Smallest /UserUnit (to 2 dp) that brings a page within the PDF limit."""
    longest = max(width_pt, height_pt)
    if longest <= PDF_MAX_PT:
        return 1.0
    return math.ceil(longest / PDF_MAX_PT * 100.0) / 100.0


def continuous_spec(cfg: AopsConfig, total_length_mm: float) -> ContinuousSpec:
    """Resolve how the continuous export will be paged."""
    height_mm = cfg.dimensions.strip_height_mm
    strategy = cfg.output.continuous_strategy

    if strategy is ContinuousStrategy.SPLIT_ROLL:
        limit = max(1.0, cfg.output.continuous_max_length_mm)
        rolls = max(1, math.ceil(total_length_mm / limit))
        roll_len = total_length_mm / rolls
        return ContinuousSpec(
            width_mm=roll_len,
            height_mm=height_mm,
            width_pt=mm_to_pt(roll_len),
            height_pt=mm_to_pt(height_mm),
            user_unit=1.0,
            over_limit=False,
            roll_count=rolls,
            roll_length_mm=roll_len,
            strategy=strategy,
        )

    width_pt = mm_to_pt(total_length_mm)
    height_pt = mm_to_pt(height_mm)
    over = max(width_pt, height_pt) > PDF_MAX_PT
    unit = user_unit_for(width_pt, height_pt) if strategy is ContinuousStrategy.USER_UNIT else 1.0

    return ContinuousSpec(
        width_mm=total_length_mm,
        height_mm=height_mm,
        width_pt=width_pt,
        height_pt=height_pt,
        user_unit=unit,
        over_limit=over,
        roll_count=1,
        roll_length_mm=total_length_mm,
        strategy=strategy,
    )


@dataclass(frozen=True, slots=True)
class DerivedGeometry:
    """All quantities derived from a configuration."""

    cell: CellSpec
    segments: tuple[Segment, ...]
    pages: tuple[PageLayout, ...]
    usable_width_um: int
    cells_per_page: int
    code_count: int
    payloads: tuple[str, ...]
    coded_length_mm: float
    total_length_mm: float
    max_position_mm: float
    distance_per_code_mm: float
    position_formula: str
    required_digits: int
    precision_loss_mm: float
    scanner: ScannerRecommendation
    accuracy: AccuracyReport
    continuous: ContinuousSpec
    matrix_cols: int
    #: Rows stacked per tiled sheet, resolved (auto-fill already applied).
    rows_per_sheet: int = 1

    @property
    def page_count(self) -> int:
        """Strip pages plus the installation guide, if enabled."""
        return len(self.pages)

    @property
    def strip_sheet_count(self) -> int:
        """Physical sheets the tiled strip occupies, rows stacked."""
        if not self.pages:
            return 0
        rows = max(1, self.rows_per_sheet)
        return -(-len(self.pages) // rows)

    @property
    def total_pdf_pages(self) -> int:
        return self.strip_sheet_count + (1 if self.instruction_page_included else 0)

    #: Set by `derive`; kept as a plain attribute for slots compatibility.
    instruction_page_included: bool = False

    def estimated_pdf_bytes(self) -> int:
        """Rough export size.

        Calibrated against a measured vector export: 421 symbols produced a
        133 KB file, i.e. ~324 bytes per symbol, plus fixed per-page furniture.
        """
        per_symbol = 324
        per_page = 3_500
        return self.code_count * per_symbol + self.total_pdf_pages * per_page + 2_000


def derive(cfg: AopsConfig, matrix_cols: int = 10) -> DerivedGeometry:
    """Compute every derived quantity for a configuration.

    `matrix_cols` is the symbol's module count across. The caller supplies it
    from the symbol layer; the default of 10 matches a Data Matrix encoding a
    payload of up to six digits, which is the common case.

    Raises `GeometryError` when the configuration cannot be laid out at all. The
    GUI never lets the user reach this because validation blocks export first.
    """
    cell = resolve_cell(cfg.dimensions)
    segments = build_segments(cfg, cell)
    usable = usable_width_um(cfg)

    try:
        pages = paginate(segments, usable)
    except GeometryError:
        pages = ()

    total_mm = um_to_mm(total_strip_length_um(segments))
    coded_mm = strip_length_mm(cfg.position, cell)

    tile_mm = um_to_mm(pages[0].content_length_um) if pages else cfg.paper.usable_width_mm()

    if cfg.output.rows_per_sheet == 0:
        rows_eff = rows_that_fit(cfg, with_calibration=cfg.output.calibration_bar)
    else:
        rows_eff = max(1, cfg.output.rows_per_sheet)

    scanner = recommend(cell, matrix_cols, cfg.scanner)
    accuracy = accuracy_report(
        cfg.media,
        cfg.printer,
        strip_length_mm=total_mm,
        tile_length_mm=tile_mm,
        calibration_length_mm=cfg.printing.calibration_length_mm,
        module_size_mm=cell.module_mm(matrix_cols),
    )

    return DerivedGeometry(
        cell=cell,
        segments=segments,
        pages=pages,
        usable_width_um=usable,
        cells_per_page=cells_per_page(cell, usable),
        code_count=code_count(cfg.position),
        payloads=all_payloads(cfg.position, cell, cfg.payload),
        coded_length_mm=coded_mm,
        total_length_mm=total_mm,
        max_position_mm=max_position_mm(cfg.position, cell),
        distance_per_code_mm=distance_per_code_mm(cell, cfg.position),
        position_formula=position_formula(cfg.position, cell),
        required_digits=required_digits(cfg.position, cell, cfg.payload),
        precision_loss_mm=precision_loss_mm(cfg.position, cell, cfg.payload),
        scanner=scanner,
        accuracy=accuracy,
        continuous=continuous_spec(cfg, total_mm),
        matrix_cols=matrix_cols,
        instruction_page_included=cfg.output.instruction_page,
        rows_per_sheet=rows_eff,
    )


def blank_slot_count(cfg: AopsConfig) -> int:
    """Number of blank cells inserted by PER_INDEX pitch mode."""
    if cfg.position.pitch_mode is PitchMode.PER_CELL:
        return 0
    span = cfg.position.end_index - cfg.position.start_index + 1
    return max(0, span - code_count(cfg.position))
