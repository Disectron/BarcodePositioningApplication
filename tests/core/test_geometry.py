"""Geometry invariants - the most important tests in the suite.

The splice property is what every other part of the application assumes: that a
page boundary never cuts a symbol, a quiet zone or a margin. It is asserted here
across a wide sweep of configurations, not just the defaults.
"""

from __future__ import annotations

import dataclasses as dc
import itertools

import pytest

from aops.core.cell import cell_invariants, resolve_cell
from aops.core.config import AopsConfig, DimensionConfig, PaperConfig, PositionConfig, PrintConfig
from aops.core.enums import Orientation, PaperPreset, PitchMode, SegmentKind
from aops.core.errors import GeometryError
from aops.core.geometry import (
    build_segments,
    cells_per_page,
    paginate,
    total_strip_length_um,
    usable_width_um,
    verify_splices,
)


def make_config(**kwargs) -> AopsConfig:
    return dc.replace(AopsConfig(), **kwargs)


# -- the splice property ----------------------------------------------------


SWEEP_PAPERS = [PaperPreset.A4, PaperPreset.A3, PaperPreset.A2]
SWEEP_MARGINS = [0.0, 5.0, 10.0, 20.0]
SWEEP_PITCH = [8.0, 10.0, 25.0, 50.0]
SWEEP_SYMBOL = [4.0, 6.0, 10.0, 20.0]
SWEEP_SCALE = [90.0, 100.0, 100.5, 101.0, 110.0]
SWEEP_COUNTS = [1, 2, 11, 12, 421]


def _sweep_cases():
    for paper, margin, pitch, symbol, scale, count in itertools.product(
        SWEEP_PAPERS, SWEEP_MARGINS, SWEEP_PITCH, SWEEP_SYMBOL, SWEEP_SCALE, SWEEP_COUNTS
    ):
        if symbol + 2.0 > pitch:  # violates the cell invariant; validation rejects it
            continue
        yield paper, margin, pitch, symbol, scale, count


@pytest.mark.parametrize("paper,margin,pitch,symbol,scale,count", list(_sweep_cases()))
def test_splice_property_holds(paper, margin, pitch, symbol, scale, count):
    """No page boundary may ever cut symbol ink, across the whole sweep."""
    cfg = make_config(
        paper=PaperConfig(preset=paper, orientation=Orientation.LANDSCAPE,
                          margin_left_mm=margin, margin_right_mm=margin),
        dimensions=DimensionConfig(pitch_mm=pitch, symbol_size_mm=symbol, quiet_zone_mm=1.0),
        position=PositionConfig(start_index=0, end_index=count - 1),
        printing=PrintConfig(scale_percent=scale),
    )
    cell = resolve_cell(cfg.dimensions)
    assert cell_invariants(cell) == ()

    usable = usable_width_um(cfg)
    segments = build_segments(cfg, cell)
    if cell.pitch_um > usable:
        with pytest.raises(GeometryError):
            paginate(segments, usable)
        return

    pages = paginate(segments, usable)
    assert verify_splices(pages, cell) == ()


@pytest.mark.parametrize("paper,margin,pitch,symbol,scale,count", list(_sweep_cases())[::7])
def test_conservation_and_atomicity(paper, margin, pitch, symbol, scale, count):
    """Segments are neither lost, duplicated, reordered nor split."""
    cfg = make_config(
        paper=PaperConfig(preset=paper, orientation=Orientation.LANDSCAPE,
                          margin_left_mm=margin, margin_right_mm=margin),
        dimensions=DimensionConfig(pitch_mm=pitch, symbol_size_mm=symbol, quiet_zone_mm=1.0),
        position=PositionConfig(start_index=0, end_index=count - 1),
        printing=PrintConfig(scale_percent=scale),
    )
    cell = resolve_cell(cfg.dimensions)
    usable = usable_width_um(cfg)
    segments = build_segments(cfg, cell)
    if cell.pitch_um > usable:
        pytest.skip("cell does not fit the page")

    pages = paginate(segments, usable)

    # Total length is conserved exactly, in integer micrometres.
    placed_total = sum(p.segment.length_um for page in pages for p in page.placed)
    assert placed_total == total_strip_length_um(segments)

    # Every cell appears exactly once, in order, and at full pitch.
    cells = [
        p.segment for page in pages for p in page.placed if p.segment.kind is SegmentKind.CELL
    ]
    original = [s for s in segments if s.kind is SegmentKind.CELL]
    assert [c.index for c in cells] == [s.index for s in original]
    assert all(c.length_um == cell.pitch_um for c in cells)

    # Page capacity is respected and page spans tile the strip.
    for page in pages:
        assert page.content_length_um <= usable
    for prev, nxt in zip(pages, pages[1:], strict=False):
        assert prev.strip_x1_um == nxt.strip_x0_um


# -- regression values ------------------------------------------------------


def test_default_pagination_regression():
    """A4 landscape, 10 mm margins, 25 mm pitch, 421 codes -> 39 sheets."""
    cfg = AopsConfig()
    cell = resolve_cell(cfg.dimensions)
    usable = usable_width_um(cfg)
    assert cells_per_page(cell, usable) == 11
    pages = paginate(build_segments(cfg, cell), usable)
    assert len(pages) == 39
    assert pages[0].cell_count == 10  # the leading margin consumes one slot
    assert pages[0].first_index == 0
    assert pages[-1].last_index == 420


def test_one_percent_scaling_costs_four_sheets():
    """Printer scaling changes pagination; it is not an emit-time detail."""
    cfg = dc.replace(AopsConfig(), printing=dc.replace(AopsConfig().printing, scale_percent=101.0))
    cell = resolve_cell(cfg.dimensions)
    usable = usable_width_um(cfg)
    assert cells_per_page(cell, usable) == 10
    assert len(paginate(build_segments(cfg, cell), usable)) == 43


def test_cell_larger_than_page_raises_not_splits():
    """A cell that cannot fit must raise, never be silently divided."""
    cfg = dc.replace(
        AopsConfig(),
        dimensions=DimensionConfig(pitch_mm=400.0, symbol_size_mm=100.0),
    )
    cell = resolve_cell(cfg.dimensions)
    with pytest.raises(GeometryError, match="does not fit"):
        paginate(build_segments(cfg, cell), usable_width_um(cfg))


def test_index_continuity_across_pages():
    cfg = AopsConfig()
    cell = resolve_cell(cfg.dimensions)
    pages = paginate(build_segments(cfg, cell), usable_width_um(cfg))
    for prev, nxt in zip(pages, pages[1:], strict=False):
        if prev.last_index is not None and nxt.first_index is not None:
            assert nxt.first_index == prev.last_index + cfg.position.increment


def test_per_index_mode_inserts_blanks():
    """PER_INDEX preserves Position = Index x Pitch by leaving blank cells."""
    cfg = dc.replace(
        AopsConfig(),
        position=PositionConfig(start_index=0, end_index=9, increment=3,
                                pitch_mode=PitchMode.PER_INDEX),
    )
    cell = resolve_cell(cfg.dimensions)
    segments = build_segments(cfg, cell)
    cells = [s for s in segments if s.kind is SegmentKind.CELL]
    blanks = [s for s in segments if s.kind is SegmentKind.BLANK]
    assert [c.index for c in cells] == [0, 3, 6, 9]
    assert len(blanks) == 6  # indices 1,2,4,5,7,8


def test_blank_segments_are_splittable_cells_are_not():
    cfg = dc.replace(
        AopsConfig(),
        position=PositionConfig(start_index=0, end_index=5, increment=2,
                                pitch_mode=PitchMode.PER_INDEX),
    )
    cell = resolve_cell(cfg.dimensions)
    for segment in build_segments(cfg, cell):
        if segment.kind is SegmentKind.CELL:
            assert not segment.splittable
            with pytest.raises(GeometryError, match="atomic"):
                segment.split(segment.length_um // 2)
        else:
            assert segment.splittable
