"""Landing the symbol on the printer's dot grid.

A thermal printer puts ink on whole dots. A module that is 11.811 dots wide
cannot be printed 11.811 dots wide - the rasteriser rounds every boundary, the
modules come out alternating 11 and 12 dots, and the symbol acquires a width
variation that no amount of extra resolution removes.

These tests pin the arithmetic and, more importantly, pin the one place where
the fix is allowed to be refused: a snap that would break the splice guarantee
must go the other way, or not happen at all.
"""

from __future__ import annotations

import dataclasses as dc

import pytest

from aops.core.config import AopsConfig, DimensionConfig
from aops.core.dotgrid import (
    DotFit,
    dots_per_module,
    fit_to_dot_grid,
    symbol_mm_for_dots,
)
from aops.core.enums import Severity
from aops.core.rules import ALL_RULES
from aops.core.stats import derive
from aops.core.units import mm_per_dot
from aops.core.validation import run_rules

#: The default geometry: a 10 mm Data Matrix, 10 modules across.
COLS = 10


# -- the arithmetic ---------------------------------------------------------


def test_the_worked_example_from_the_module_docstring():
    """10 mm / 10 modules at 300 dpi is 11.811 dots. The whole point."""
    assert dots_per_module(10.0, COLS, 300) == pytest.approx(11.811, abs=1e-3)
    assert symbol_mm_for_dots(12, COLS, 300) == pytest.approx(10.16, abs=1e-3)


def test_dots_and_size_are_inverses():
    for dpi in (203, 300, 600):
        for dots in (4, 8, 12, 24):
            size = symbol_mm_for_dots(dots, COLS, dpi)
            assert dots_per_module(size, COLS, dpi) == pytest.approx(dots)


@pytest.mark.parametrize("bad", [(0.0, COLS, 300), (10.0, 0, 300), (10.0, COLS, 0)])
def test_degenerate_inputs_give_zero_not_an_exception(bad):
    assert dots_per_module(*bad) == 0.0


def test_203_dpi_is_already_on_grid_for_a_millimetre_module():
    """7.992 dots is 8 for every purpose that matters - eight thousandths of a
    dot is 0.0001 mm of ink, and offering to "fix" it would be noise."""
    fit = fit_to_dot_grid(10.0, COLS, 203)
    assert fit.module_dots == pytest.approx(7.992, abs=1e-3)
    assert fit.is_on_grid
    assert not fit.has_fix
    assert fit.module_variation_percent == 0.0
    assert fit.grid_deviation_mm == 0.0


def test_the_variation_is_one_dot_expressed_as_a_percentage():
    fit = fit_to_dot_grid(10.0, COLS, 300)
    assert not fit.is_on_grid
    assert fit.module_variation_percent == pytest.approx(100.0 / 11.811, abs=1e-2)
    assert fit.grid_deviation_mm == pytest.approx(mm_per_dot(300) / 2)


def test_more_resolution_shrinks_the_defect_but_never_removes_it():
    """The argument against "just print at 600 dpi"."""
    at300 = fit_to_dot_grid(10.0, COLS, 300)
    at600 = fit_to_dot_grid(10.0, COLS, 600)
    assert not at300.is_on_grid
    assert not at600.is_on_grid
    assert at600.module_variation_percent < at300.module_variation_percent
    assert at600.module_variation_percent > 0.0


def test_a_snapped_size_is_itself_on_grid():
    """Otherwise applying the fix would leave the warning showing."""
    for dpi in (203, 300, 600, 305):
        fit = fit_to_dot_grid(10.0, COLS, dpi)
        again = fit_to_dot_grid(fit.snapped_symbol_mm, COLS, dpi)
        assert again.is_on_grid, dpi
        assert not again.has_fix, dpi


# -- the constraint that outranks it ---------------------------------------


def test_the_snap_goes_down_rather_than_break_the_splice_clearance():
    """A printing defect is a better outcome than a strip that cannot be cut."""
    # 12 dots would be 10.160 mm, over the ceiling; 11 dots is 9.313 mm.
    fit = fit_to_dot_grid(10.0, COLS, 300, max_symbol_mm=10.05)
    assert fit.snapped_down
    assert fit.snapped_dots == 11
    assert fit.snapped_symbol_mm == pytest.approx(9.313, abs=1e-3)
    assert fit.snapped_symbol_mm <= 10.05


def test_a_snap_is_never_suggested_above_the_ceiling():
    for ceiling in (9.0, 9.5, 10.05, 10.2, 12.0):
        fit = fit_to_dot_grid(10.0, COLS, 300, max_symbol_mm=ceiling)
        assert fit.snapped_symbol_mm <= ceiling + 5e-4, ceiling


def test_no_suggestion_at_all_when_nothing_legal_exists():
    """Better to say so than to offer a size that fails a different check."""
    fit = fit_to_dot_grid(10.0, COLS, 300, max_symbol_mm=0.5, min_module_mm=0.3)
    assert fit.snapped_symbol_mm == 0.0
    assert not fit.has_fix
    # The measurement of the problem survives even with no fix to offer.
    assert fit.module_dots > 0.0
    assert not fit.is_on_grid


def test_the_floor_on_module_size_is_respected():
    fit = fit_to_dot_grid(10.0, COLS, 300, max_symbol_mm=4.0, min_module_mm=0.3)
    if fit.snapped_symbol_mm > 0.0:
        assert fit.snapped_symbol_mm / COLS >= 0.3 - 1e-6


def test_size_change_is_zero_when_there_is_nothing_to_change_to():
    assert DotFit(300, COLS, 10.0, 11.811, 0, 0.0, False).size_change_mm == 0.0


# -- the rule --------------------------------------------------------------


def _findings(cfg: AopsConfig, rule_id: str):
    try:
        derived = derive(cfg)
    except Exception:
        derived = None
    return [f for f in run_rules(ALL_RULES, cfg, derived).findings if f.rule_id == rule_id]


def _at_dpi(dpi: int, **dims) -> AopsConfig:
    cfg = AopsConfig()
    return dc.replace(
        cfg,
        printer=dc.replace(cfg.printer, dpi=dpi),
        dimensions=DimensionConfig(**dims) if dims else cfg.dimensions,
    )


def test_the_rule_is_silent_on_grid_and_speaks_off_it():
    assert _findings(_at_dpi(203), "PRN-010") == []
    assert _findings(_at_dpi(300), "PRN-010") != []


def test_the_rule_never_blocks_the_export():
    """A dot-grid mismatch degrades the print; it does not make it unusable."""
    cfg = _at_dpi(300)
    report = run_rules(ALL_RULES, cfg, derive(cfg))
    assert "PRN-010" in {f.rule_id for f in report.findings}
    assert not report.blocks_export


def test_the_severity_is_graded_by_how_bad_the_mismatch_is():
    """A 4% spread and a 25% spread are not the same conversation.

    Flat WARNING for both was the first version of this rule, and it would have
    warned on the shipped default for an effect of 0.02 of a module - which is
    ISO 15415 grade A on grid non-uniformity by a wide margin.
    """
    gentle = _findings(_at_dpi(600), "PRN-010")  # 23.6 dots/module, 4.2%
    assert gentle and gentle[0].severity is Severity.INFO

    # A 1.2 mm code over 10 modules at 203 dpi is 4.7 dots per module.
    harsh = _findings(_at_dpi(203, pitch_mm=25.0, symbol_size_mm=1.2), "PRN-010")
    assert harsh and harsh[0].severity is Severity.WARNING


def test_the_shipped_default_does_not_warn():
    """A default configuration that warns out of the box trains people to ignore
    warnings. It may still carry a note."""
    report = run_rules(ALL_RULES, AopsConfig(), derive(AopsConfig()))
    warned = [f for f in report.findings
              if f.rule_id == "PRN-010" and f.severity >= Severity.WARNING]
    assert warned == []


def test_the_offered_fix_actually_clears_the_finding():
    """The test that would have caught a fix computed from the wrong ceiling."""
    cfg = _at_dpi(300)
    finding = _findings(cfg, "PRN-010")[0]
    assert finding.fix is not None

    fixed = dc.replace(
        cfg, dimensions=dc.replace(cfg.dimensions, symbol_size_mm=finding.fix.value)
    )
    assert _findings(fixed, "PRN-010") == []


def test_applying_the_fix_does_not_break_a_different_rule():
    """Growing the code by 0.16 mm must not push it into the quiet zones."""
    cfg = _at_dpi(300)
    finding = _findings(cfg, "PRN-010")[0]
    fixed = dc.replace(
        cfg, dimensions=dc.replace(cfg.dimensions, symbol_size_mm=finding.fix.value)
    )
    report = run_rules(ALL_RULES, cfg, derive(cfg))
    after = run_rules(ALL_RULES, fixed, derive(fixed))
    assert not after.blocks_export
    # No new blocking rule appeared that was not there before.
    assert {f.rule_id for f in after.blocking} <= {f.rule_id for f in report.blocking}


def test_the_message_quotes_both_numbers_the_user_needs():
    finding = _findings(_at_dpi(300), "PRN-010")[0]
    assert "11.811" in finding.message  # what it is
    assert "10.160" in (finding.hint or "")  # what to make it


def test_a_tight_pitch_gets_a_downward_snap_and_says_why():
    """Rounding up here would cost the splice guarantee, so it must not.

    Pitch 12.1 with 1.0 mm quiet zones leaves a 10.100 mm ceiling, so the
    12-dot size (10.160 mm) is out of reach and the snap has to go to 11 dots.
    A pitch of 12.2 would leave 10.200 mm and snap up perfectly legally - the
    margin here is thirty microns wide, which is why it is a named test.
    """
    cfg = _at_dpi(300, pitch_mm=12.1, symbol_size_mm=10.0, quiet_zone_mm=1.0)
    finding = _findings(cfg, "PRN-010")[0]
    assert finding.fix is not None
    assert finding.fix.value < 10.0
    assert "down" in (finding.hint or "").lower()

    fixed = dc.replace(
        cfg, dimensions=dc.replace(cfg.dimensions, symbol_size_mm=finding.fix.value)
    )
    assert not run_rules(ALL_RULES, fixed, derive(fixed)).blocks_export


def test_the_rule_is_quiet_when_the_geometry_did_not_resolve():
    cfg = _at_dpi(300, pitch_mm=0.0, symbol_size_mm=10.0)
    assert _findings(cfg, "PRN-010") == []


@pytest.mark.parametrize("dpi", [150, 203, 300, 305, 600, 1200])
def test_no_dpi_produces_a_fix_that_fails_its_own_check(dpi: int):
    """Swept because the failure mode is a rounding boundary, not a case."""
    cfg = _at_dpi(dpi)
    for finding in _findings(cfg, "PRN-010"):
        if finding.fix is None:
            continue
        fixed = dc.replace(
            cfg, dimensions=dc.replace(cfg.dimensions, symbol_size_mm=finding.fix.value)
        )
        assert _findings(fixed, "PRN-010") == [], f"{dpi} dpi fix did not settle"
