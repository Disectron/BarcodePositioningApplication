"""Composers for strip pages and the continuous strip.

These build `DrawList`s only. Nothing here knows whether the result will end up
in a PDF or on screen.
"""

from __future__ import annotations

from dataclasses import replace

from aops.core.config import AopsConfig
from aops.core.drawlist import (
    DrawList,
    Line,
    PageDrawLists,
    Primitive,
    Rect,
    SymbolPrim,
    Text,
)
from aops.core.enums import PageScope, SegmentKind
from aops.core.geometry import PageLayout
from aops.core.layout import style as S
from aops.core.layout.bands import solve_bands, solve_sheet_bands
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

    if cfg.output.page_header_footer:
        items += header_elements(
            f"SHEET {page.strip_page_number}/{total_pages}",
            cfg,
            content_w,
            bands.header_baseline_mm,
            measurer=measurer,
        )

    # Faint outline of the strip band, so the installer can see what to cut to.
    # It is the same cut guide the cut marks are, so it follows the same switch:
    # a print with nothing to cut should carry no cutting ink.
    if cfg.printing.cut_marks:
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

    if cfg.output.page_header_footer:
        left, right = page_footer_text(
            page, total_pages, cfg, fingerprint, _page_position_range(page, cfg, derived)
        )
        items += footer_elements(
            left, right, content_w, bands.footer_baseline_mm, measurer=measurer
        )

    sheet_items = registration_marks(sheet_w, sheet_h, cfg.printing)

    return PageDrawLists(
        sheet=DrawList(sheet_w, sheet_h, tuple(sheet_items)),
        content=DrawList(content_w, bands.total_height_mm, tuple(items)),
    )


def compose_multirow_sheet(
    sheet_pages: tuple[PageLayout, ...],
    sheet_number: int,
    total_sheets: int,
    cfg: AopsConfig,
    derived: DerivedGeometry,
    matrices: dict[str, ModuleMatrix],
    fingerprint: str,
    *,
    measurer: TextMeasurer | None = None,
) -> PageDrawLists:
    """Compose one sheet carrying several consecutive strip rows.

    A row is exactly what a single-row page is - the pagination and the splice
    guarantee are untouched; only the stacking is new. Header, footer and the
    calibration bar belong to the sheet; each row carries its own caption,
    outline, cells, ruler and cut marks, because after cutting, a row is a
    physical object on its own and must identify itself.
    """
    measurer = measurer or DEFAULT_METRICS
    sheet_w, sheet_h = cfg.paper.sheet_size_mm()
    content_w = cfg.paper.usable_width_mm()

    with_cal = cfg.output.calibration_bar and (
        cfg.output.calibration_scope is PageScope.EVERY_PAGE or sheet_number == 1
    )
    sb = solve_sheet_bands(cfg, len(sheet_pages), with_calibration=with_cal)
    row = sb.row

    items: list[Primitive] = []
    payload_map = _payload_map(cfg, derived)
    total_rows = len(derived.pages)

    if cfg.output.page_header_footer:
        items += header_elements(
            f"SHEET {sheet_number}/{total_sheets}",
            cfg,
            content_w,
            sb.header_baseline_mm,
            measurer=measurer,
        )

    for page, top in zip(sheet_pages, sb.row_tops_mm, strict=True):
        length_mm = um_to_mm(page.content_length_um)
        strip_top = top + row.strip_top_mm
        strip_bottom = top + row.strip_bottom_mm

        pos0, pos1 = _page_position_range(page, cfg, derived)
        codes = (
            f"CODES {page.first_index}-{page.last_index}"
            if page.first_index is not None
            else "CODES (none)"
        )
        # Caption baseline sits in the upper half of the caption zone; the
        # alignment arrows live in the lower half (strip_top - 2), so the
        # two share the zone without colliding.
        items.append(Text(
            0.0, top - 3.8,
            f"ROW {page.strip_page_number}/{total_rows}   {codes}   "
            f"X {page.strip_x0_mm:.1f}-{page.strip_x1_mm:.1f} mm   "
            f"POS {pos0:.1f}-{pos1:.1f} mm",
            S.FOOTER,
        ))

        if cfg.printing.cut_marks:
            items.append(Rect(0.0, strip_top, length_mm, row.strip_height_mm, S.STRIP_OUTLINE))

        items += strip_cells(
            page, derived.cell, matrices, payload_map, cfg, strip_top, measurer=measurer,
        )

        if row.ruler_y_mm is not None:
            items += ruler_elements(
                page.strip_x0_mm, page.strip_x1_mm, top + row.ruler_y_mm, measurer=measurer,
            )

        for x in (0.0, length_mm):
            items += cut_marks(x, strip_top, strip_bottom, cfg.printing)

        items += alignment_arrows(0.0, length_mm, strip_top - 2.0, cfg.printing)

    # The cutting zones between rows. Dashed, full content width, labelled -
    # the rows above and below already say what they are; this line only has
    # to say "separate them here".
    for y in sb.cut_line_ys_mm:
        items.append(Line(4.0, y, content_w, y, S.CUT_LINE))
        items.append(Text(0.0, y + 1.0, "CUT", S.RULER_LABEL))

    if with_cal and sb.calibration_y_mm is not None:
        items += calibration_elements(0.0, sb.calibration_y_mm, cfg.printing, measurer=measurer)

    if cfg.output.page_header_footer:
        first, last = sheet_pages[0], sheet_pages[-1]
        p0, _ = _page_position_range(first, cfg, derived)
        _, p1 = _page_position_range(last, cfg, derived)
        left = (
            f"SHEET {sheet_number:02d}/{total_sheets:02d}   "
            f"ROWS {first.strip_page_number}-{last.strip_page_number}/{total_rows}   "
            f"X {first.strip_x0_mm:.1f}-{last.strip_x1_mm:.1f} mm   "
            f"POS {p0:.1f}-{p1:.1f} mm"
        )
        right = f"REV {cfg.project.revision or '-'}   {fingerprint}"
        items += footer_elements(left, right, content_w, sb.footer_baseline_mm, measurer=measurer)

    sheet_items = registration_marks(sheet_w, sheet_h, cfg.printing)

    return PageDrawLists(
        sheet=DrawList(sheet_w, sheet_h, tuple(sheet_items)),
        content=DrawList(content_w, sb.total_height_mm, tuple(items)),
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

    if cfg.printing.cut_marks:
        items.append(
            Rect(
                0.0, bands.strip_top_mm, spec.roll_length_mm, bands.strip_height_mm,
                S.STRIP_OUTLINE,
            )
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

    if cfg.output.page_header_footer:
        label = (
            f"ROLL {roll_index + 1}/{spec.roll_count}" if spec.roll_count > 1 else "CONTINUOUS"
        )
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
