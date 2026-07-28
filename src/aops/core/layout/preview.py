"""The on-screen strip preview.

Bounded to the first N symbols regardless of how many the strip contains. That
is the whole performance strategy for the interactive path: rendering ten Data
Matrix symbols costs about three milliseconds cold and nothing at all once
cached, no matter whether the strip has 40 codes or 5000.

The preview renders the *print* palette - black ink on a white page - because an
engineer needs to see what will come out of the printer, not a dark-mode
rendering of it.
"""

from __future__ import annotations

from dataclasses import replace

from aops.core.config import AopsConfig
from aops.core.drawlist import DrawList, Primitive, Rect, SymbolPrim, Text
from aops.core.enums import HrPosition
from aops.core.layout import style as S
from aops.core.layout.bands import solve_bands
from aops.core.layout.elements import calibration_elements, ruler_elements
from aops.core.matrix import ModuleMatrix
from aops.core.stats import DerivedGeometry
from aops.core.text_metrics import DEFAULT_METRICS, TextMeasurer
from aops.core.units import um_to_mm

DEFAULT_PREVIEW_SYMBOLS = 10


def compose_preview(
    cfg: AopsConfig,
    derived: DerivedGeometry,
    matrices: dict[str, ModuleMatrix],
    *,
    max_symbols: int = DEFAULT_PREVIEW_SYMBOLS,
    measurer: TextMeasurer | None = None,
) -> DrawList:
    """Compose a preview of the first `max_symbols` cells."""
    measurer = measurer or DEFAULT_METRICS
    cell = derived.cell
    shown = min(max_symbols, derived.code_count)
    width = max(cell.pitch_mm * max(shown, 1), cfg.printing.calibration_length_mm + 4.0)

    bands = solve_bands(cfg, with_calibration=cfg.output.calibration_bar)
    items: list[Primitive] = [
        Rect(0.0, 0.0, width, bands.total_height_mm, S.PAGE_FILL),
        Rect(0.0, bands.strip_top_mm, cell.pitch_mm * shown, bands.strip_height_mm, S.STRIP_OUTLINE),
    ]

    hr_style = replace(S.HUMAN_READABLE, size_pt=cfg.output.hr_font_pt)

    for i in range(shown):
        payload = derived.payloads[i]
        matrix = matrices.get(payload)
        x = i * cell.pitch_mm + cell.margin_lr_mm
        y = bands.strip_top_mm + um_to_mm(cell.symbol_y_offset_um)

        if matrix is not None:
            items.append(SymbolPrim(x, y, cell.symbol_mm, matrix))
        else:
            # Placeholder box while the encoder is unavailable, so the layout is
            # still legible and the user can see the geometry is right.
            items.append(Rect(x, y, cell.symbol_mm, cell.symbol_mm, S.STRIP_OUTLINE))

        if cfg.output.human_readable:
            w = measurer.width_mm(payload, hr_style.role, hr_style.size_pt)
            centre = i * cell.pitch_mm + cell.pitch_mm / 2.0
            ty = (
                y + cell.symbol_mm + hr_style.size_pt * 0.50
                if cfg.output.hr_position is HrPosition.BELOW
                else y - hr_style.size_pt * 0.20
            )
            items.append(Text(centre - w / 2.0, ty, payload, hr_style))

    if bands.ruler_y_mm is not None:
        items += ruler_elements(0.0, cell.pitch_mm * max(shown, 1), bands.ruler_y_mm,
                                measurer=measurer)

    if cfg.output.calibration_bar and bands.calibration_y_mm is not None:
        items += calibration_elements(0.0, bands.calibration_y_mm, cfg.printing, measurer=measurer)

    return DrawList(width, bands.total_height_mm, tuple(items))
