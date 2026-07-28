"""Label-printer roll media and direct thermal.

A thermal-transfer label printer on continuous polyester is arguably the right
device for this job rather than a fallback: the media is continuous, so the
strip prints in one piece and the whole splice problem - cutting accuracy,
per-tile datum alignment, accumulated scale error - simply does not arise.

These tests pin the geometry down, because the trap is quiet: the printed page
is the entire band stack, not the strip band, and at the defaults that is over
twice as tall. A roll wide enough for the strip can still clip the artwork.
"""

from __future__ import annotations

import dataclasses as dc

import pytest

from aops.core.config import AopsConfig, MediaConfig, OutputConfig, PaperConfig
from aops.core.enums import PaperPreset, PrintMethod, Ribbon, Severity
from aops.core.layout.bands import solve_bands
from aops.core.rules import ALL_RULES
from aops.core.stats import derive
from aops.core.validation import run_rules

ROLLS = [p for p in PaperPreset if p.is_roll]


def cfg_with(**kwargs) -> AopsConfig:
    return dc.replace(AopsConfig(), **kwargs)


def roll_cfg(preset: PaperPreset, *, margin: float = 3.0, continuous: bool = True) -> AopsConfig:
    return cfg_with(
        paper=PaperConfig(
            preset=preset,
            margin_left_mm=margin,
            margin_right_mm=margin,
            margin_top_mm=margin,
            margin_bottom_mm=margin,
        ),
        output=OutputConfig(tiled_pages=not continuous, continuous=continuous),
    )


def findings(cfg: AopsConfig, rule_id: str):
    report = run_rules(ALL_RULES, cfg, derive(cfg))
    return [f for f in report.findings if f.rule_id == rule_id]


# -- the presets themselves -------------------------------------------------


def test_roll_presets_exist_and_are_flagged():
    assert ROLLS, "no roll presets registered"
    for preset in ROLLS:
        assert preset.is_roll
        assert preset.roll_width_mm > 0.0


def test_sheet_presets_are_not_rolls():
    for preset in (PaperPreset.A4, PaperPreset.A3, PaperPreset.CUSTOM):
        assert not preset.is_roll
        assert preset.roll_width_mm == 0.0


def test_every_preset_declares_a_size():
    """A missing dict entry would KeyError deep inside pagination."""
    for preset in PaperPreset:
        width, height = preset.portrait_mm
        assert width > 0 and height > 0
        assert preset.display_name


def test_roll_display_names_state_the_printable_width():
    assert PaperPreset.ROLL_4IN.roll_width_mm == 104.0
    assert "104" in PaperPreset.ROLL_4IN.display_name
    assert '4"' in PaperPreset.ROLL_4IN.display_name


def test_rolls_are_ordered_by_width():
    widths = [p.roll_width_mm for p in ROLLS]
    assert widths == sorted(widths)


# -- roll geometry ----------------------------------------------------------


def test_the_band_stack_not_the_strip_band_is_what_must_fit():
    """The trap this rule exists for: 40 mm strip, 92 mm printed page."""
    cfg = roll_cfg(PaperPreset.ROLL_4IN)
    bands = solve_bands(cfg, with_calibration=cfg.output.calibration_bar)
    assert bands.total_height_mm > 2 * cfg.dimensions.strip_height_mm


def test_four_inch_roll_at_default_margins_is_caught():
    """84 mm usable against a 92 mm band stack - the edges would be clipped."""
    cfg = roll_cfg(PaperPreset.ROLL_4IN, margin=10.0)
    found = findings(cfg, "PAG-010")
    assert found and found[0].severity is Severity.ERROR


def test_four_inch_roll_with_slim_margins_fits():
    assert not findings(roll_cfg(PaperPreset.ROLL_4IN, margin=3.0), "PAG-010")


def test_narrow_roll_is_rejected_even_with_no_margins():
    assert findings(roll_cfg(PaperPreset.ROLL_2IN, margin=0.0), "PAG-010")


def test_wide_roll_fits_comfortably():
    assert not findings(roll_cfg(PaperPreset.ROLL_6IN, margin=10.0), "PAG-010")


def test_roll_width_check_applies_to_continuous_output():
    """pag_height only covers tiled output, so this is the only guard there."""
    cfg = roll_cfg(PaperPreset.ROLL_4IN, margin=10.0, continuous=True)
    assert not cfg.output.tiled_pages
    assert findings(cfg, "PAG-010")


# -- steering towards continuous --------------------------------------------


def test_tiling_onto_a_roll_warns():
    """Cutting up continuous media is the worst of both worlds."""
    cfg = roll_cfg(PaperPreset.ROLL_4IN, continuous=False)
    found = findings(cfg, "PAG-008")
    assert found and found[0].severity is Severity.WARNING


def test_continuous_on_a_roll_is_reported_as_splice_free():
    found = findings(roll_cfg(PaperPreset.ROLL_4IN), "PAG-009")
    assert found and found[0].severity is Severity.INFO
    assert "one piece" in found[0].message


def test_sheet_media_raises_no_roll_findings():
    cfg = cfg_with(paper=PaperConfig(preset=PaperPreset.A4))
    for rule_id in ("PAG-008", "PAG-009", "PAG-010"):
        assert not findings(cfg, rule_id)


# -- direct thermal ---------------------------------------------------------


def test_direct_thermal_warns_about_fading():
    cfg = cfg_with(media=MediaConfig(method=PrintMethod.DIRECT_THERMAL, ribbon=Ribbon.NONE))
    found = findings(cfg, "MED-009")
    assert found and found[0].severity is Severity.WARNING


def test_direct_thermal_does_not_demand_a_ribbon():
    """The thermal-transfer 'ribbon required' error must not fire here."""
    cfg = cfg_with(media=MediaConfig(method=PrintMethod.DIRECT_THERMAL, ribbon=Ribbon.NONE))
    assert not [f for f in findings(cfg, "MED-004") if f.severity is Severity.ERROR]


def test_direct_thermal_with_a_ribbon_says_it_is_ignored():
    cfg = cfg_with(media=MediaConfig(method=PrintMethod.DIRECT_THERMAL, ribbon=Ribbon.RESIN))
    assert findings(cfg, "MED-010")


def test_only_thermal_transfer_uses_a_ribbon():
    assert PrintMethod.THERMAL_TRANSFER.uses_ribbon
    for method in PrintMethod:
        if method is not PrintMethod.THERMAL_TRANSFER:
            assert not method.uses_ribbon


def test_every_print_method_has_a_display_name():
    for method in PrintMethod:
        assert method.display_name


# -- the whole path ---------------------------------------------------------


@pytest.mark.parametrize("preset", [PaperPreset.ROLL_4IN, PaperPreset.ROLL_6IN])
def test_roll_config_paginates_and_derives(preset: PaperPreset):
    derived = derive(roll_cfg(preset))
    assert derived.code_count > 0
    assert derived.total_length_mm > 0.0


def test_roll_media_does_not_block_export():
    """Roll guidance is advice, not a refusal - a valid roll job must export."""
    cfg = roll_cfg(PaperPreset.ROLL_4IN, margin=3.0)
    assert not run_rules(ALL_RULES, cfg, derive(cfg)).blocks_export
