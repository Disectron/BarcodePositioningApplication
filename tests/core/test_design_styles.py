"""Print styles - presets over the page-furniture switches.

The design decision under test is that a style is *derived*, never stored.
Storing both a style and the switches it controls would let them disagree, and
the disagreement would be invisible: the combo would claim "Plain" while the
sheet printed a calibration bar. So every test here that round-trips a style
goes through the switches, not through a remembered value.
"""

from __future__ import annotations

import dataclasses as dc

import pytest

from aops.core.config import AopsConfig, PositionConfig
from aops.core.design import (
    PRESET_STYLES,
    STYLE_FLAGS,
    apply_style,
    detect_style,
    matches_style,
)
from aops.core.enums import PrintStyle, Severity
from aops.core.layout.bands import solve_bands
from aops.core.layout.strip import compose_strip_page
from aops.core.project_io import dump_project, load_project
from aops.core.rules import ALL_RULES
from aops.core.stats import derive
from aops.core.validation import run_rules
from aops.symbols.cache import SymbolCache
from aops.symbols.registry import build_registry

SHORT = dc.replace(AopsConfig(), position=PositionConfig(start_index=0, end_index=20))


def findings(cfg: AopsConfig, rule_id: str):
    report = run_rules(ALL_RULES, cfg, derive(cfg))
    return [f for f in report.findings if f.rule_id == rule_id]


def first_page_primitives(cfg: AopsConfig) -> int:
    derived = derive(cfg)
    cache = SymbolCache(build_registry(cfg.symbol))
    matrices = {p: cache.get(cfg.symbol.symbology, p) for p in derived.payloads}
    page = compose_strip_page(derived.pages[0], cfg, derived, matrices, "test0000")
    return len(page.content.items) + len(page.sheet.items)


# -- derivation is the whole point ------------------------------------------


@pytest.mark.parametrize("style", PRESET_STYLES)
def test_applying_a_style_makes_it_detectable(style: PrintStyle):
    assert detect_style(apply_style(SHORT, style)) is style


@pytest.mark.parametrize("style", PRESET_STYLES)
def test_applying_a_style_is_idempotent(style: PrintStyle):
    once = apply_style(SHORT, style)
    assert apply_style(once, style) == once


def test_the_default_configuration_is_the_engineering_style():
    assert detect_style(AopsConfig()) is PrintStyle.ENGINEERING


def test_touching_one_switch_moves_the_style_to_custom():
    cfg = apply_style(SHORT, PrintStyle.ENGINEERING)
    cfg = dc.replace(cfg, output=dc.replace(cfg.output, calibration_bar=False))
    assert detect_style(cfg) is PrintStyle.CUSTOM


def test_custom_is_never_reported_for_a_preset_configuration():
    for style in PRESET_STYLES:
        assert detect_style(apply_style(SHORT, style)) is not PrintStyle.CUSTOM


def test_applying_custom_changes_nothing():
    """CUSTOM is a report, not a preset."""
    cfg = apply_style(SHORT, PrintStyle.PLAIN)
    assert apply_style(cfg, PrintStyle.CUSTOM) == cfg


def test_presets_are_mutually_exclusive():
    for style in PRESET_STYLES:
        cfg = apply_style(SHORT, style)
        assert [s for s in PRESET_STYLES if matches_style(cfg, s)] == [style]


def test_every_style_declares_a_name_and_description():
    for style in PrintStyle:
        assert style.display_name
        assert style.description


def test_presets_all_control_the_same_switches():
    """A switch listed in one preset but not another would be left dangling."""
    keys = {
        style: {(sec, f) for sec, ch in flags.items() for f in ch}
        for style, flags in STYLE_FLAGS.items()
    }
    assert len(set(map(frozenset, keys.values()))) == 1


# -- what actually reaches the page -----------------------------------------


def test_plain_prints_symbols_and_nothing_else():
    """One primitive per cell on the page - no outline, marks, text or bands.

    Counted from the page's own cells rather than `cells_per_page`: the first
    page also carries the leading margin, so it holds one fewer than a bare
    page would.
    """
    cfg = apply_style(SHORT, PrintStyle.PLAIN)
    derived = derive(cfg)
    assert first_page_primitives(cfg) == derived.pages[0].cell_count


def test_labelled_adds_exactly_one_label_per_symbol():
    """Plus the two splice boundaries: Labelled keeps cut marks off but still
    has a multi-sheet strip to assemble, so each page carries its two labelled
    trim edges - 4 primitives each (three line segments and the label)."""
    plain = first_page_primitives(apply_style(SHORT, PrintStyle.PLAIN))
    labelled = first_page_primitives(apply_style(SHORT, PrintStyle.LABELLED))
    assert labelled == 2 * plain + 8


def test_engineering_draws_substantially_more():
    plain = first_page_primitives(apply_style(SHORT, PrintStyle.PLAIN))
    full = first_page_primitives(apply_style(SHORT, PrintStyle.ENGINEERING))
    assert full > plain * 5


def test_plain_more_than_halves_the_band_stack():
    """Removing the bands, not merely blanking them, is what buys the height."""
    def height(style: PrintStyle) -> float:
        cfg = apply_style(SHORT, style)
        return solve_bands(cfg, with_calibration=cfg.output.calibration_bar).total_height_mm

    assert height(PrintStyle.PLAIN) < height(PrintStyle.ENGINEERING) / 2


def test_plain_leaves_room_for_the_strip_band_itself():
    cfg = apply_style(SHORT, PrintStyle.PLAIN)
    bands = solve_bands(cfg, with_calibration=False)
    assert bands.total_height_mm >= cfg.dimensions.strip_height_mm
    assert bands.strip_top_mm >= 0.0


def test_no_style_drops_the_instruction_guide_from_engineering():
    assert apply_style(SHORT, PrintStyle.ENGINEERING).output.instruction_page


# -- what a plain print gives up --------------------------------------------


def test_plain_warns_that_scale_cannot_be_checked():
    found = findings(apply_style(SHORT, PrintStyle.PLAIN), "PAG-011")
    assert found and found[0].severity is Severity.WARNING


def test_labelled_warns_too():
    assert findings(apply_style(SHORT, PrintStyle.LABELLED), "PAG-011")


def test_engineering_raises_no_style_warning():
    cfg = apply_style(SHORT, PrintStyle.ENGINEERING)
    assert not findings(cfg, "PAG-011")
    assert not findings(cfg, "PAG-012")


def test_multi_sheet_plain_warns_that_sheets_are_indistinguishable():
    cfg = apply_style(SHORT, PrintStyle.PLAIN)
    assert len(derive(cfg).pages) > 1
    assert findings(cfg, "PAG-012")


def test_single_sheet_plain_does_not_warn_about_sheet_identity():
    cfg = apply_style(
        dc.replace(SHORT, position=PositionConfig(start_index=0, end_index=3)),
        PrintStyle.PLAIN,
    )
    assert len(derive(cfg).pages) == 1
    assert not findings(cfg, "PAG-012")


def test_a_plain_print_still_exports():
    """Artwork is a legitimate output; the warnings must not block it."""
    cfg = apply_style(SHORT, PrintStyle.PLAIN)
    assert not run_rules(ALL_RULES, cfg, derive(cfg)).blocks_export


# -- persistence ------------------------------------------------------------


@pytest.mark.parametrize("style", PRESET_STYLES)
def test_style_survives_a_project_round_trip(style: PrintStyle):
    cfg = apply_style(SHORT, style)
    restored = load_project(dump_project(cfg, app_version="test")).config
    assert detect_style(restored) is style


def test_a_file_without_the_new_switch_reads_as_engineering():
    """Old projects predate page_header_footer and must keep their behaviour."""
    text = dump_project(AopsConfig(), app_version="test")
    stripped = text.replace('"page_header_footer": true,', "")
    assert "page_header_footer" not in stripped
    restored = load_project(stripped).config
    assert restored.output.page_header_footer is True
    assert detect_style(restored) is PrintStyle.ENGINEERING
