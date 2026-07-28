"""Composers for strip pages and the continuous strip.

These build `DrawList`s only. Nothing here knows whether the result will end up
in a PDF or on screen.
"""

from __future__ import annotations

from dataclasses import replace

from aops.core.config import AopsConfig
from aops.core.drawlist import DrawList, PageDrawLists, Primitive, Rect, SymbolPrim, Text
from aops.core.enums import PageScope, SegmentKind
from aops.core.geometry import PageLayout
from aops.core.layout import style as S
from aops.core.layout.bands import solve_bands
from aops.core.layout.elements import (
    alignment_arrows,
    calibration_elements,
    cut_marks,
    footer_elements,
    header_elements,
    page_footer_text,
    registration_marks,
    ruler_elements,
    strip_cells,
)
from aops.core.matrix import ModuleMatrix
from aops.core.positions import position_mm
from aops.core.stats import DerivedGeometry
from aops.core.text_metrics import DEFAULT_METRICS, TextMeasurer
from aops.core.units import um_to_mm


def _payload_map(cfg: AopsConfig, derived: DerivedGeometry) -> dict[int, str]:
    from aops.core.positions import code_indices

    return dict(zip(code_indices(cfg.position), derived.payloads, strict=False))


def _page_position_range(
    page: PageLayout, cfg: AopsConfig, derived: DerivedGeometry
) -> tuple[float, float]:
    if page.first_index is None or page.last_index is None:
        return (0.0, 0.0)
    a = position_mm(page.first_index, cfg.position, derived.cell)
    b = position_mm(page.last_index, cfg.position, derived.cell)
    return (min(a, b), max(a, b))


def compose_strip_page(
    page: PageLayout,
    cfg: AopsConfig,
    derived: DerivedGeometry,
    matrices: dict[str, ModuleMatrix],
    fingerprint: str,
    *,
    measurer: TextMeasurer | None = None,
) -> PageDrawLists:
    """Compose one tiled strip page."""
    measurer = measurer or DEFAULT_METRICS
    sheet_w, sheet_h = cfg.paper.sheet_size_mm()
    content_w = cfg.paper.usable_width_mm()

    with_cal = cfg.output.calibration_bar and (
        cfg.output.calibration_scope is PageScope.EVERY_PAGE or page.strip_page_number == 1
    )
    bands = solve_bands(cfg, with_calibration=with_cal)

    items: list[Primitive] = []
    total_pages = len(derived.pages)

    items += header_elements(
        f"SHEET {page.strip_page_number}/{total_pages}",
        cfg,
        content_w,
        bands.header_baseline_mm,
        measurer=measurer,
    )

    # Faint outline of the strip band, so the installer can see what to cut to.
    items.append(
        Rect(
            0.0,
            bands.strip_top_mm,
            um_to_mm(page.content_length_um),
            bands.strip_height_mm,
            S.STRIP_OUTLINE,
        )
    )

    items += strip_cells(
        page, derived.cell, matrices, _payload_map(cfg, derived), cfg,
        bands.strip_top_mm, measurer=measurer,
    )

    if bands.ruler_y_mm is not None:
        items += ruler_elements(
            page.strip_x0_mm,
            page.strip_x1_mm,
            bands.ruler_y_mm,
            measurer=measurer,
        )

    if with_cal and bands.calibration_y_mm is not None:
        items += calibration_elements(0.0, bands.calibration_y_mm, cfg.printing, measurer=measurer)

    # Cut marks at the page's own boundaries - both fall in white by construction.
    for x in (0.0, um_to_mm(page.content_length_um)):
        items += cut_marks(x, bands.strip_top_mm, bands.strip_bottom_mm, cfg.printing)

    items += alignment_arrows(
        0.0, um_to_mm(page.content_length_um), bands.strip_top_mm - 2.0, cfg.printing
    )

    left, right = page_footer_text(
        page, total_pages, cfg, fingerprint, _page_position_range(page, cfg, derived)
    )
    items += footer_elements(left, right, content_w, bands.footer_baseline_mm, measurer=measurer)

    sheet_items = registration_marks(sheet_w, sheet_h, cfg.printing)

    return PageDrawLists(
        sheet=DrawList(sheet_w, sheet_h, tuple(sheet_items)),
        content=DrawList(content_w, bands.total_height_mm, tuple(items)),
    )


def compose_continuous(
    cfg: AopsConfig,
    derived: DerivedGeometry,
    matrices: dict[str, ModuleMatrix],
    fingerprint: str,
    *,
    roll_index: int = 0,
    measurer: TextMeasurer | None = None,
) -> PageDrawLists:
    """Compose the whole strip as one continuous page (or one roll of a split).

    Unlike the tiled export there are no page breaks, so the strip is laid out
    against a single continuous coordinate system and every segment is placed at
    its absolute position.
    """
    measurer = measurer or DEFAULT_METRICS
    spec = derived.continuous

    x0_mm = roll_index * spec.roll_length_mm
    x1_mm = x0_mm + spec.roll_length_mm

    bands = solve_bands(cfg, with_calibration=cfg.output.calibration_bar)
    items: list[Primitive] = []

    items.append(
        Rect(0.0, bands.strip_top_mm, spec.roll_length_mm, bands.strip_height_mm, S.STRIP_OUTLINE)
    )

    payloads = _payload_map(cfg, derived)
    cell = derived.cell
    cursor_um = 0
    hr_style = replace(S.HUMAN_READABLE, size_pt=cfg.output.hr_font_pt)
    for seg in derived.segments:
        seg_x0_mm = um_to_mm(cursor_um)
        cursor_um += seg.length_um
        if seg.kind is not SegmentKind.CELL or seg.index is None:
            continue
        if not (x0_mm - cell.pitch_mm <= seg_x0_mm < x1_mm):
            continue
        payload = payloads.get(seg.index)
        matrix = matrices.get(payload) if payload else None
        if matrix is None:
            continue
        local_x = seg_x0_mm - x0_mm + cell.margin_lr_mm
        y = bands.strip_top_mm + um_to_mm(cell.symbol_y_offset_um)
        items.append(SymbolPrim(local_x, y, cell.symbol_mm, matrix))
        if cfg.output.human_readable:
            w = measurer.width_mm(payload, hr_style.role, cfg.output.hr_font_pt)
            centre = seg_x0_mm - x0_mm + cell.pitch_mm / 2.0
            items.append(
                Text(centre - w / 2.0, y + cell.symbol_mm + cfg.output.hr_font_pt * 0.5,
                     payload, hr_style)
            )

    if bands.ruler_y_mm is not None:
        items += ruler_elements(x0_mm, x1_mm, bands.ruler_y_mm, measurer=measurer)

    if cfg.output.calibration_bar and bands.calibration_y_mm is not None:
        items += calibration_elements(0.0, bands.calibration_y_mm, cfg.printing, measurer=measurer)

    label = f"ROLL {roll_index + 1}/{spec.roll_count}" if spec.roll_count > 1 else "CONTINUOUS"
    items += header_elements(label, cfg, spec.roll_length_mm, bands.header_baseline_mm,
                             measurer=measurer)
    items += footer_elements(
        f"{label}   X {x0_mm:.1f}-{x1_mm:.1f} mm   {derived.code_count} CODES",
        f"REV {cfg.project.revision or '-'}   {fingerprint}",
        spec.roll_length_mm,
        bands.footer_baseline_mm,
        measurer=measurer,
    )

    height = max(bands.total_height_mm, spec.height_mm)
    return PageDrawLists(
        sheet=DrawList(spec.roll_length_mm, height, ()),
        content=DrawList(spec.roll_length_mm, height, tuple(items)),
    )
