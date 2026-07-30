"""Fitting a real reader to the strip.

Until a reader's datasheet figures are entered, the tool works from a generic
lens estimate and cannot say whether any particular unit will do the job. Given
an angular field of view the mounting distance follows exactly, and the focus
window then decides whether that distance is one the reader can actually use.

The failure this guards against is the quiet one: a reader that reads a code
perfectly on the bench but cannot cover a whole spacing plus a code from any
distance it can focus at, so the machine has blind spots where position is lost.
"""

from __future__ import annotations

import dataclasses as dc
from math import radians, tan

import pytest

from aops.core.config import AopsConfig, DimensionConfig, ScannerConfig
from aops.core.enums import Severity
from aops.core.presets import READER_GROUP, READER_PRESETS, apply
from aops.core.rules import ALL_RULES
from aops.core.stats import derive
from aops.core.validation import run_rules

NVF230 = READER_PRESETS[0]


def with_reader(**overrides) -> AopsConfig:
    base = {
        "fov_angle_deg": 48.5,
        "fov_vertical_deg": 30.7,
        "dof_min_mm": 50.0,
        "dof_max_mm": 200.0,
        "sensor_px_h": 1280,
    }
    base.update(overrides)
    return dc.replace(AopsConfig(), scanner=ScannerConfig(**base))


def scn_findings(cfg: AopsConfig, rule_id: str):
    return [f for f in run_rules(ALL_RULES, cfg, derive(cfg)).findings if f.rule_id == rule_id]


# -- the geometry -----------------------------------------------------------


def test_without_a_reader_spec_nothing_is_claimed():
    """The generic estimate must stay in charge until real figures arrive."""
    rec = derive(AopsConfig()).scanner
    assert not rec.has_reader_spec
    assert rec.required_wd_mm == 0.0


def test_mounting_distance_follows_from_the_view_angle():
    """A view of angle t spans 2*tan(t/2) per unit distance."""
    cfg = with_reader()
    rec = derive(cfg).scanner
    expected = rec.fov_continuous_mm / (2 * tan(radians(48.5 / 2)))
    assert rec.required_wd_mm == pytest.approx(expected)


def test_a_wider_view_angle_needs_less_distance():
    near = derive(with_reader(fov_angle_deg=70.0)).scanner.required_wd_mm
    far = derive(with_reader(fov_angle_deg=30.0)).scanner.required_wd_mm
    assert near < far


def test_a_bigger_pitch_pushes_the_reader_further_back():
    """The requirement is driven by pitch, which is the whole FOV insight."""
    def wd(pitch: float) -> float:
        cfg = with_reader()
        cfg = dc.replace(cfg, dimensions=DimensionConfig(pitch_mm=pitch, symbol_size_mm=10.0))
        return derive(cfg).scanner.required_wd_mm

    assert wd(50.0) > wd(25.0)


def test_vertical_view_is_reported_at_the_required_distance():
    rec = derive(with_reader()).scanner
    expected = rec.required_wd_mm * 2 * tan(radians(30.7 / 2))
    assert rec.vertical_fov_mm == pytest.approx(expected)


def test_pixels_per_module_come_from_the_stated_sensor():
    rec = derive(with_reader()).scanner
    assert rec.available_px_per_module == pytest.approx(
        1280 / rec.fov_continuous_mm * rec.module_size_mm
    )


def test_an_unstated_sensor_reports_no_pixel_figure():
    assert derive(with_reader(sensor_px_h=0)).scanner.available_px_per_module == 0.0


# -- the verdicts -----------------------------------------------------------


def test_a_geometry_beyond_the_focus_range_is_an_error():
    """The quiet failure: readable on the bench, blind spots on the machine."""
    cfg = dc.replace(
        with_reader(),
        dimensions=DimensionConfig(pitch_mm=200.0, symbol_size_mm=40.0,
                                   quiet_zone_mm=4.0, strip_height_mm=60.0),
    )
    found = scn_findings(cfg, "SCN-003")
    assert found and found[0].severity is Severity.ERROR
    assert run_rules(ALL_RULES, cfg, derive(cfg)).blocks_export


def test_needing_less_than_the_minimum_focus_is_only_informational():
    """Closer than minimum focus just means mount further back; harmless."""
    found = scn_findings(with_reader(), "SCN-004")
    assert found and found[0].severity is Severity.INFO


def test_a_reader_that_cannot_see_the_code_height_is_an_error():
    cfg = dc.replace(with_reader(fov_vertical_deg=2.0))
    found = scn_findings(cfg, "SCN-005")
    assert found and found[0].severity is Severity.ERROR


def test_too_few_pixels_per_module_warns():
    cfg = dc.replace(with_reader(sensor_px_h=64))
    found = scn_findings(cfg, "SCN-006")
    assert found and found[0].severity is Severity.WARNING


def test_reading_one_code_at_a_time_is_flagged_as_no_redundancy():
    found = scn_findings(with_reader(), "SCN-007")
    assert found and found[0].severity is Severity.INFO


def test_reading_several_codes_removes_that_note():
    assert not scn_findings(with_reader(min_codes_in_view=3), "SCN-007")


def test_none_of_this_fires_without_a_reader_spec():
    for rule_id in ("SCN-003", "SCN-004", "SCN-005", "SCN-006", "SCN-007"):
        assert not scn_findings(AopsConfig(), rule_id), rule_id


# -- the shipped readers ---------------------------------------------------


@pytest.mark.parametrize("preset", READER_PRESETS, ids=lambda p: p.name)
def test_reader_presets_only_touch_the_scanner(preset):
    assert preset.sections() == ("scanner",)


@pytest.mark.parametrize("preset", READER_PRESETS, ids=lambda p: p.name)
def test_reader_presets_state_their_source(preset):
    """These are the only vendor figures in the project; each must be traceable."""
    assert "Figures from" in preset.description
    assert "datasheet" in preset.description


@pytest.mark.parametrize("preset", READER_PRESETS, ids=lambda p: p.name)
def test_reader_presets_are_grouped(preset):
    assert preset.group == READER_GROUP


@pytest.mark.parametrize("preset", READER_PRESETS, ids=lambda p: p.name)
def test_reader_presets_produce_a_mounting_distance(preset):
    rec = derive(apply(preset, AopsConfig())).scanner
    assert rec.has_reader_spec
    assert rec.required_wd_mm > 0.0


def test_the_nvf230_covers_every_shipped_code_size():
    """The reader the strip was specified around must work at all of them."""
    from aops.core.presets import SIZE_PRESETS

    base = apply(NVF230, AopsConfig())
    for size in SIZE_PRESETS:
        cfg = apply(size, base)
        blocking = run_rules(ALL_RULES, cfg, derive(cfg)).blocking
        assert not blocking, f"{size.name}: {[f.rule_id for f in blocking]}"


def test_the_nvf230_stays_inside_its_focus_window_at_the_largest_code():
    from aops.core.presets import SIZE_PRESETS

    cfg = apply(SIZE_PRESETS[-1], apply(NVF230, AopsConfig()))
    rec = derive(cfg).scanner
    assert cfg.scanner.dof_min_mm <= rec.required_wd_mm <= cfg.scanner.dof_max_mm


def test_the_nvf230_resolves_far_more_than_the_target():
    """Coarse position codes are nowhere near this reader's resolution limit."""
    rec = derive(apply(NVF230, AopsConfig())).scanner
    assert rec.available_px_per_module > 5 * 5.0


# -- a fixed mounting distance ---------------------------------------------


def at_distance(wd: float, **overrides) -> AopsConfig:
    cfg = with_reader(mount_distance_mm=wd, **overrides)
    return dc.replace(
        cfg,
        dimensions=DimensionConfig(pitch_mm=55.0, symbol_size_mm=40.0,
                                   quiet_zone_mm=4.0, strip_height_mm=60.0),
    )


def test_a_distance_of_zero_leaves_the_forward_calculation_alone():
    """The original behaviour has to survive untouched."""
    rec = derive(with_reader()).scanner
    assert not rec.distance_is_fixed
    assert rec.available_fov_mm == 0.0
    assert rec.required_wd_mm > 0.0


def test_the_window_follows_from_distance_and_angle():
    rec = derive(at_distance(120.0)).scanner
    assert rec.available_fov_mm == pytest.approx(120.0 * 2 * tan(radians(48.5 / 2)))


def test_the_window_grows_with_distance():
    near = derive(at_distance(80.0)).scanner.available_fov_mm
    far = derive(at_distance(160.0)).scanner.available_fov_mm
    assert far == pytest.approx(2 * near)


def test_headroom_is_what_is_left_after_the_geometry():
    rec = derive(at_distance(120.0)).scanner
    assert rec.fov_headroom_mm == pytest.approx(rec.available_fov_mm - rec.fov_continuous_mm)
    assert rec.fits_at_distance


def test_too_close_does_not_fit_and_is_blocking():
    cfg = at_distance(100.0)
    rec = derive(cfg).scanner
    assert not rec.fits_at_distance
    assert run_rules(ALL_RULES, cfg, derive(cfg)).blocks_export
    assert scn_findings(cfg, "SCN-009")


def test_the_max_pitch_actually_fits():
    """The suggested spacing must be one that clears the finding it answers."""
    cfg = at_distance(100.0)
    target = derive(cfg).scanner.max_pitch_mm
    fixed = dc.replace(cfg, dimensions=dc.replace(cfg.dimensions, pitch_mm=target))
    assert derive(fixed).scanner.fits_at_distance
    assert not scn_findings(fixed, "SCN-009")


def test_the_max_code_size_actually_fits():
    cfg = at_distance(100.0)
    rec = derive(cfg).scanner
    symbol = rec.max_symbol_mm
    quiet = symbol / 10.0
    fixed = dc.replace(
        cfg,
        dimensions=DimensionConfig(pitch_mm=symbol + 2 * quiet, symbol_size_mm=symbol,
                                   quiet_zone_mm=quiet, strip_height_mm=symbol * 2),
    )
    assert derive(fixed).scanner.fits_at_distance


def test_no_zero_pitch_is_ever_suggested():
    """At 30 mm the window cannot hold the code at all - the pitch is not at fault."""
    cfg = at_distance(30.0)
    found = scn_findings(cfg, "SCN-009")
    assert found
    assert found[0].fix is None
    assert "cannot hold this code at all" in found[0].hint


def test_an_unfocusable_distance_is_an_error_with_a_fix():
    for wd, expected in ((30.0, 50.0), (250.0, 200.0)):
        found = scn_findings(at_distance(wd), "SCN-008")
        assert found and found[0].severity is Severity.ERROR
        assert found[0].fix is not None
        assert found[0].fix.value == pytest.approx(expected)


def test_spare_window_is_reported_as_available_resolution():
    found = scn_findings(at_distance(190.0), "SCN-010")
    assert found and found[0].severity is Severity.INFO


def test_spare_window_is_not_reported_where_the_reader_cannot_focus():
    """Saying "you have room to spare" about an unusable distance is noise."""
    assert not scn_findings(at_distance(250.0), "SCN-010")


def test_a_vertical_shortfall_at_the_fixed_distance_is_an_error():
    found = scn_findings(at_distance(60.0, fov_vertical_deg=10.0), "SCN-011")
    assert found and found[0].severity is Severity.ERROR


def test_the_forward_rules_go_quiet_once_a_distance_is_pinned():
    """Both would tell the same story; only one should."""
    for rule_id in ("SCN-003", "SCN-004", "SCN-005"):
        assert not scn_findings(at_distance(120.0), rule_id), rule_id


def test_a_distance_alone_fires_nothing_without_a_reader_spec():
    cfg = dc.replace(AopsConfig(), scanner=ScannerConfig(mount_distance_mm=120.0))
    for rule_id in ("SCN-008", "SCN-009", "SCN-010", "SCN-011"):
        assert not scn_findings(cfg, rule_id), rule_id
