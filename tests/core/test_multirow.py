"""Multi-row tiling: several strip rows stacked on one sheet.

THE INVARIANT THAT MAKES THIS SAFE
----------------------------------
A row IS a page. The multi-row feature regroups the pagination's existing
pages onto shared sheets; it does not repaginate. Row boundaries are therefore
page boundaries, every cut falls in white by the same proof as before, and
`verify_splices` runs unchanged at export. The tests here defend the stacking
arithmetic and the sheet composition - the splice guarantee needs no new
defence because nothing it depends on moved.
"""

from __future__ import annotations

import dataclasses as dc

import pytest

from aops.core.config import AopsConfig, DimensionConfig, PositionConfig
from aops.core.drawlist import Line, Text
from aops.core.enums import PageScope, Severity
from aops.core.layout.bands import (
    ROW_CAPTION_H_MM,
    rows_that_fit,
    solve_bands,
    solve_sheet_bands,
)
from aops.core.layout.strip import compose_multirow_sheet
from aops.core.project_io import config_fingerprint
from aops.core.rules import ALL_RULES
from aops.core.stats import derive
from aops.core.validation import run_rules
from aops.symbols.cache import SymbolCache
from aops.symbols.registry import build_registry

A = AopsConfig


def dense() -> AopsConfig:
    """A short dense job: 20 mm band, labelled style, 61 codes at 25 mm."""
    cfg = A()
    return dc.replace(
        cfg,
        dimensions=DimensionConfig(pitch_mm=25.0, symbol_size_mm=10.0,
                                   strip_height_mm=20.0),
        position=PositionConfig(start_index=0, end_index=60),
        output=dc.replace(cfg.output, engineering_ruler=False),
    )


def derived_and_matrices(cfg):
    d = derive(cfg)
    cache = SymbolCache(build_registry(cfg.symbol))
    matrices = {p: cache.get(cfg.symbol.symbology, p) for p in dict.fromkeys(d.payloads)}
    return d, matrices


# -- the stacking arithmetic ------------------------------------------------


def test_row_tops_ascend_and_cut_lines_sit_between_them():
    sb = solve_sheet_bands(A(), 3, with_calibration=True)
    assert len(sb.row_tops_mm) == 3
    assert list(sb.row_tops_mm) == sorted(sb.row_tops_mm)
    assert len(sb.cut_line_ys_mm) == 2
    for cut, (above, below) in zip(
        sb.cut_line_ys_mm, zip(sb.row_tops_mm, sb.row_tops_mm[1:], strict=False),
        strict=True,
    ):
        assert above < cut < below


def test_the_row_block_is_the_single_row_layout_without_sheet_furniture():
    """A row inside a sheet must lay out exactly like a furniture-free page."""
    cfg = A()
    bare = solve_bands(
        dc.replace(cfg, output=dc.replace(cfg.output, page_header_footer=False)),
        with_calibration=False,
    )
    sb = solve_sheet_bands(cfg, 2, with_calibration=False)
    assert sb.row == bare


def test_total_height_grows_by_exactly_one_row_block():
    two = solve_sheet_bands(A(), 2, with_calibration=True)
    three = solve_sheet_bands(A(), 3, with_calibration=True)
    per_row = three.row.total_height_mm
    grew = three.total_height_mm - two.total_height_mm
    assert grew == pytest.approx(per_row + ROW_CAPTION_H_MM + 5.0)  # + ROW_GAP


def test_rows_that_fit_matches_the_layout_it_predicts():
    """The capacity claim must be self-consistent: the predicted count fits
    the usable height and one more row does not."""
    for cfg in (A(), dense()):
        fit = rows_that_fit(cfg, with_calibration=True)
        usable = cfg.paper.usable_height_mm()
        assert solve_sheet_bands(cfg, fit, with_calibration=True).total_height_mm <= usable
        assert (
            solve_sheet_bands(cfg, fit + 1, with_calibration=True).total_height_mm
            > usable
        )


def test_a_dense_band_fits_many_rows_and_a_tiny_sheet_still_gets_one():
    assert rows_that_fit(dense(), with_calibration=True) >= 4
    from aops.core.enums import PaperPreset

    tiny = dc.replace(
        A(),
        paper=dc.replace(A().paper, preset=PaperPreset.CUSTOM,
                         custom_width_mm=80.0, custom_height_mm=60.0),
    )
    assert rows_that_fit(tiny, with_calibration=True) == 1


def test_sheet_count_derives_from_rows():
    cfg = dc.replace(dense(), output=dc.replace(dense().output, rows_per_sheet=0))
    d = derive(cfg)
    assert d.rows_per_sheet >= 4
    expected = -(-len(d.pages) // d.rows_per_sheet)
    assert d.strip_sheet_count == expected
    assert d.total_pdf_pages == expected + 1  # + guide page
    # The classic default is untouched: one row per sheet.
    assert derive(dense()).strip_sheet_count == len(derive(dense()).pages)


# -- the sheet composition --------------------------------------------------


def texts(items):
    return [i.text for i in items if isinstance(i, Text)]


def test_every_row_identifies_itself_and_cuts_are_marked():
    cfg = dense()
    d, matrices = derived_and_matrices(cfg)
    rows = d.pages[:3]
    lists = compose_multirow_sheet(
        tuple(rows), 1, 2, cfg, d, matrices, config_fingerprint(cfg)
    )
    labels = texts(lists.content.items)
    row_captions = [t for t in labels if t.startswith("ROW ")]
    # Captions for each row, plus the CUT marks between them.
    assert len(row_captions) == 3
    for caption in row_captions:
        assert "X " in caption and "POS " in caption
    assert labels.count("CUT") == 2
    dashed = [
        i for i in lists.content.items
        if isinstance(i, Line) and i.style.dash_mm
    ]
    assert len(dashed) >= 2


def test_symbols_land_at_distinct_row_offsets():
    from aops.core.drawlist import SymbolPrim

    cfg = dense()
    d, matrices = derived_and_matrices(cfg)
    lists = compose_multirow_sheet(
        tuple(d.pages[:3]), 1, 2, cfg, d, matrices, config_fingerprint(cfg)
    )
    ys = sorted({round(i.y, 1) for i in lists.content.items if isinstance(i, SymbolPrim)})
    assert len(ys) == 3  # one symbol row per strip row


def test_the_calibration_bar_prints_once_per_scope_not_per_row():
    cfg = dc.replace(
        dense(),
        output=dc.replace(dense().output,
                          calibration_scope=PageScope.FIRST_PAGE),
    )
    d, matrices = derived_and_matrices(cfg)
    fp = config_fingerprint(cfg)

    first = compose_multirow_sheet(tuple(d.pages[:3]), 1, 2, cfg, d, matrices, fp)
    second = compose_multirow_sheet(tuple(d.pages[3:5]), 2, 2, cfg, d, matrices, fp)
    assert any("MUST MEASURE" in t for t in texts(first.content.items))
    assert not any("MUST MEASURE" in t for t in texts(second.content.items))


def test_the_sheet_footer_spans_the_rows_it_carries():
    cfg = dense()
    d, matrices = derived_and_matrices(cfg)
    lists = compose_multirow_sheet(
        tuple(d.pages[:3]), 1, 2, cfg, d, matrices, config_fingerprint(cfg)
    )
    footer = next(t for t in texts(lists.content.items) if t.startswith("SHEET 01/02"))
    assert "ROWS 1-3" in footer


def test_content_height_matches_the_band_solver():
    cfg = dense()
    d, matrices = derived_and_matrices(cfg)
    lists = compose_multirow_sheet(
        tuple(d.pages[:2]), 1, 3, cfg, d, matrices, config_fingerprint(cfg)
    )
    sb = solve_sheet_bands(cfg, 2, with_calibration=True)
    assert lists.content.height_mm == pytest.approx(sb.total_height_mm)


def test_no_row_draws_outside_the_content_width():
    """The regression the first multi-row render caught: rulers drew at
    ABSOLUTE strip x, so every row after the first landed off the sheet.

    The bug predates multi-row - page two of any single-row export had it -
    but one page per sheet meant nobody had printed page two yet.
    """
    cfg = A()  # ruler enabled by default
    d, matrices = derived_and_matrices(cfg)
    lists = compose_multirow_sheet(
        tuple(d.pages[:2]), 1, 1, cfg, d, matrices, config_fingerprint(cfg)
    )
    slack = 1.0
    for item in lists.content.items:
        if isinstance(item, Line):
            assert max(item.x1, item.x2) <= lists.content.width_mm + slack, item


def test_single_row_pages_after_the_first_keep_their_ruler_on_the_page():
    """Same regression, on the classic layout it has been hiding in."""
    from aops.core.layout.strip import compose_strip_page

    cfg = A()
    d, matrices = derived_and_matrices(cfg)
    page2 = d.pages[1]
    assert page2.strip_x0_mm > 0  # the case where absolute != local
    lists = compose_strip_page(page2, cfg, d, matrices, config_fingerprint(cfg))
    for item in lists.content.items:
        if isinstance(item, Line):
            assert max(item.x1, item.x2) <= lists.content.width_mm + 1.0, item


# -- the export -------------------------------------------------------------


def test_multirow_export_writes_fewer_sheets_with_the_same_codes(tmp_path):
    from aops.render.pdf.export import export_tiled
    from aops.symbols.cache import SymbolCache

    # Guide page off, so the page counts are exactly the sheet counts and
    # the comparison carries no slack (the guide itself can span two pages).
    cfg = dc.replace(dense(), output=dc.replace(dense().output, instruction_page=False))
    cache = SymbolCache(build_registry(cfg.symbol))

    single = export_tiled(cfg, derive(cfg), cache, tmp_path / "single.pdf")
    assert single.page_count == len(derive(cfg).pages)

    stacked_cfg = dc.replace(cfg, output=dc.replace(cfg.output, rows_per_sheet=0))
    stacked = export_tiled(
        stacked_cfg, derive(stacked_cfg), cache, tmp_path / "stacked.pdf"
    )

    assert stacked.page_count < single.page_count
    d = derive(stacked_cfg)
    assert stacked.page_count == d.strip_sheet_count
    assert stacked.path.stat().st_size > 0
    # Decode verification ran on the stacked export too.
    assert stacked.verified_count > 0


def test_an_explicit_row_count_is_honoured(tmp_path):
    from aops.render.pdf.export import export_tiled

    cfg = dc.replace(dense(), output=dc.replace(dense().output, rows_per_sheet=2,
                                                instruction_page=False))
    cache = SymbolCache(build_registry(cfg.symbol))
    result = export_tiled(cfg, derive(cfg), cache, tmp_path / "two.pdf")
    d = derive(cfg)
    assert result.page_count == -(-len(d.pages) // 2)


# -- the rule ---------------------------------------------------------------


def test_too_many_rows_is_an_error_with_a_one_click_way_out():
    cfg = dc.replace(A(), output=dc.replace(A().output, rows_per_sheet=10))
    report = run_rules(ALL_RULES, cfg, derive(cfg))
    finding = next(f for f in report.findings if f.rule_id == "PAG-013")
    assert finding.severity is Severity.ERROR
    assert finding.fix is not None and finding.fix.value == 0

    fixed = dc.replace(cfg, output=dc.replace(cfg.output, rows_per_sheet=0))
    fixed_report = run_rules(ALL_RULES, fixed, derive(fixed))
    assert "PAG-013" not in {f.rule_id for f in fixed_report.findings}


def test_single_row_and_auto_never_trip_the_rule():
    for rows in (0, 1):
        cfg = dc.replace(A(), output=dc.replace(A().output, rows_per_sheet=rows))
        report = run_rules(ALL_RULES, cfg, derive(cfg))
        assert "PAG-013" not in {f.rule_id for f in report.findings}
