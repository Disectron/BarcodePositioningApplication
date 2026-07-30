"""Reading the strip while the axis moves.

Every number here traces to the NLS-NVF230 user guide, because the alternative
is inventing a motion model and presenting it as engineering:

* S7.8 "Enhancing Motion Tolerance": t[us] = 25.4 x (width in mils) / v[m/s]
* S4.7.1 "Exposure Setting": exposure range 60-60000 us, default 1000
* S5.1.2 "Burst Mode": length = range[mm] / speed[mm/s] x 1000 / 20

The first two give the blur limit, the third gives the frame rate. The most
important test in this file is the one that shows the vendor formula and this
module's arithmetic are the same statement in different units.
"""

from __future__ import annotations

import dataclasses as dc

import pytest

from aops.core.config import AopsConfig, DimensionConfig
from aops.core.enums import Severity
from aops.core.motion import (
    EXPOSURE_DEFAULT_US,
    EXPOSURE_MIN_US,
    FRAME_INTERVAL_MS,
    blur_limited_speed,
    exposure_for_speed,
    frame_limited_speed,
    frames_on_a_code,
    motion_limits,
)
from aops.core.presets import BUILT_IN_PRESETS
from aops.core.presets import apply as apply_preset
from aops.core.rules import ALL_RULES
from aops.core.stats import derive
from aops.core.validation import run_rules

MM_PER_MIL = 0.0254


def vendor_exposure_us(module_mm: float, speed_m_per_s: float) -> float:
    """The formula exactly as the user guide prints it, in its own units."""
    return 25.4 * (module_mm / MM_PER_MIL) / speed_m_per_s


# -- the blur limit ---------------------------------------------------------


@pytest.mark.parametrize("module_mm", [0.254, 0.5, 1.0, 2.5])
@pytest.mark.parametrize("speed_m_per_s", [0.1, 0.5, 1.0, 5.0])
def test_this_module_agrees_with_the_vendor_formula(module_mm, speed_m_per_s):
    """Same statement, different units. If this drifts, the model is wrong."""
    mine = exposure_for_speed(module_mm, speed_m_per_s * 1000.0)
    assert mine == pytest.approx(vendor_exposure_us(module_mm, speed_m_per_s), rel=1e-9)


def test_the_vendor_formula_spends_exactly_one_module_of_smear():
    """What the formula is really saying, and the reason it can be inverted."""
    for module_mm in (0.254, 1.0, 2.0):
        for speed_mm_per_s in (100.0, 1000.0, 4000.0):
            t_us = exposure_for_speed(module_mm, speed_mm_per_s)
            smear_mm = speed_mm_per_s * (t_us / 1e6)
            assert smear_mm == pytest.approx(module_mm, rel=1e-9)


def test_the_headline_case_a_millimetre_module_at_the_default_exposure():
    """1.000 mm modules at the reader's own default tolerate 1.0 m/s."""
    assert blur_limited_speed(1.0, EXPOSURE_DEFAULT_US) == pytest.approx(1000.0)


def test_speed_and_exposure_are_inverses():
    for module_mm in (0.5, 1.0, 1.6):
        for exposure in (60, 250, 1000, 12000):
            speed = blur_limited_speed(module_mm, exposure)
            assert exposure_for_speed(module_mm, speed) == pytest.approx(exposure)


def test_a_bigger_module_buys_speed_in_proportion():
    """Module size is a motion decision, not only a print-resolution one."""
    assert blur_limited_speed(2.0, 1000) == pytest.approx(
        2 * blur_limited_speed(1.0, 1000)
    )


@pytest.mark.parametrize("bad", [(0.0, 1000), (1.0, 0), (-1.0, 1000), (1.0, -5)])
def test_blur_limit_is_zero_rather_than_infinite_when_unknown(bad):
    """Zero reads as "not computable"; an infinity would read as "no limit"."""
    assert blur_limited_speed(*bad) == 0.0


# -- the frame limit --------------------------------------------------------


def test_the_frame_interval_comes_from_the_burst_mode_formula():
    """1000/20 in the vendor formula is milliseconds per frame."""
    assert FRAME_INTERVAL_MS == 20.0
    # 90 mm window, one frame wanted: 90 mm in 20 ms is 4500 mm/s.
    assert frame_limited_speed(90.0, 1) == pytest.approx(4500.0)


def test_asking_for_more_frames_costs_speed_proportionally():
    one = frame_limited_speed(90.0, 1)
    assert frame_limited_speed(90.0, 2) == pytest.approx(one / 2)
    assert frame_limited_speed(90.0, 3) == pytest.approx(one / 3)


def test_frames_on_a_code_is_fractional_not_floored():
    """Below one frame the fraction is the useful number - it is the risk."""
    caught = frames_on_a_code(90.0, 6000.0)
    assert 0.0 < caught < 1.0
    assert caught == pytest.approx(90.0 / 6000.0 * 1000.0 / 20.0)


def test_a_stationary_axis_is_not_a_frame_problem():
    assert frames_on_a_code(90.0, 0.0) == 0.0


# -- the two together ------------------------------------------------------


def test_the_lower_limit_binds_and_is_named():
    """A message that says which ceiling it is tells the user what to change."""
    # Small module, wide window: exposure binds.
    blur_bound = motion_limits(module_mm=0.3, fov_mm=400.0, exposure_us=1000)
    assert blur_bound.limited_by == "exposure"

    # Large module, narrow window: the frame rate binds.
    frame_bound = motion_limits(module_mm=5.0, fov_mm=30.0, exposure_us=1000)
    assert frame_bound.limited_by == "frame rate"


def test_an_unknown_limit_does_not_win_by_being_zero():
    """min() over a list containing 0.0 would report a limit of zero."""
    limits = motion_limits(module_mm=1.0, fov_mm=0.0, exposure_us=1000)
    assert limits.frame_speed_mm_per_s == 0.0
    assert limits.max_speed_mm_per_s == pytest.approx(1000.0)
    assert limits.limited_by == "exposure"


def test_nothing_known_reports_no_limit_and_no_name():
    limits = motion_limits(module_mm=0.0, fov_mm=0.0)
    assert limits.max_speed_mm_per_s == 0.0
    assert limits.limited_by == ""
    assert limits.fits  # cannot claim a violation it cannot compute


def test_headroom_and_fit_agree_with_each_other():
    limits = motion_limits(
        module_mm=1.0, fov_mm=90.0, exposure_us=1000, requested_speed_mm_per_s=500.0
    )
    assert limits.fits
    assert limits.headroom == pytest.approx(2.0)

    tight = dc.replace(limits, requested_speed_mm_per_s=2000.0)
    assert not tight.fits
    assert tight.headroom < 1.0


def test_an_unspecified_speed_always_fits():
    """Zero means "read standing still", not "zero millimetres per second"."""
    limits = motion_limits(module_mm=1.0, fov_mm=90.0, requested_speed_mm_per_s=0.0)
    assert not limits.is_specified
    assert limits.fits
    assert limits.smear_mm == 0.0


def test_the_exposure_floor_is_recognised_as_unreachable():
    """Past the floor the answer is a bigger code, not a shorter exposure."""
    fast = motion_limits(
        module_mm=0.3, fov_mm=1000.0, requested_speed_mm_per_s=20_000.0
    )
    assert fast.exposure_needed_us < EXPOSURE_MIN_US
    assert not fast.exposure_is_reachable


# -- the rules -------------------------------------------------------------


def _reader_cfg(**scanner) -> AopsConfig:
    """The NVF230 preset at a 100 mm mounting distance - the manual's own case."""
    preset = next(p for p in BUILT_IN_PRESETS if "NVF230" in p.name)
    cfg = apply_preset(preset, AopsConfig())
    return dc.replace(
        cfg,
        scanner=dc.replace(cfg.scanner, mount_distance_mm=100.0, **scanner),
    )


def _ids(cfg: AopsConfig) -> set[str]:
    return {f.rule_id for f in run_rules(ALL_RULES, cfg, derive(cfg)).findings}


def test_the_manual_worked_example_reproduces():
    """User guide p.30: NVF230-SR at H=100 mm sees 90 x 55 mm.

    The preset's angles came from the product page; this is the manual
    independently confirming them, which is the only reason to trust either.
    """
    cfg = _reader_cfg()
    rec = derive(cfg).scanner
    assert rec.available_fov_mm == pytest.approx(90.0, abs=0.5)
    assert rec.available_fov_v_mm == pytest.approx(55.0, abs=0.5)


def test_motion_rules_are_silent_until_a_speed_is_entered():
    """Most strips are read standing still; a speed limit would be noise."""
    quiet = _ids(_reader_cfg(axis_speed_mm_per_s=0.0))
    assert not {"SCN-012", "SCN-013", "SCN-014"} & quiet


def test_a_comfortable_speed_is_reported_not_warned_about():
    ids = _ids(_reader_cfg(axis_speed_mm_per_s=200.0))
    assert "SCN-014" in ids
    assert "SCN-012" not in ids
    assert "SCN-013" not in ids


def test_too_much_smear_warns_and_offers_a_shorter_exposure():
    cfg = _reader_cfg(axis_speed_mm_per_s=2000.0)
    findings = [f for f in run_rules(ALL_RULES, cfg, derive(cfg)).findings
                if f.rule_id == "SCN-012"]
    assert findings
    finding = findings[0]
    assert finding.severity is Severity.WARNING
    assert finding.fix is not None
    assert finding.fix.field == "scanner.exposure_us"
    assert finding.fix.value == 500  # 1.000 mm module at 2000 mm/s


def test_the_offered_exposure_actually_clears_the_finding():
    cfg = _reader_cfg(axis_speed_mm_per_s=2000.0)
    finding = next(f for f in run_rules(ALL_RULES, cfg, derive(cfg)).findings
                   if f.rule_id == "SCN-012")
    fixed = dc.replace(
        cfg, scanner=dc.replace(cfg.scanner, exposure_us=finding.fix.value)
    )
    assert "SCN-012" not in _ids(fixed)


def test_no_exposure_is_offered_when_none_would_be_legal():
    """A 0.3 mm module at 10 m/s needs 30 us; the reader floors at 60."""
    cfg = _reader_cfg(axis_speed_mm_per_s=10_000.0)
    cfg = dc.replace(
        cfg, dimensions=DimensionConfig(pitch_mm=25.0, symbol_size_mm=3.0)
    )
    finding = next(f for f in run_rules(ALL_RULES, cfg, derive(cfg)).findings
                   if f.rule_id == "SCN-012")
    assert finding.fix is None
    assert "floor" in (finding.hint or "")


def test_missing_a_code_entirely_is_an_error_not_a_warning():
    """Below one frame per code, position is lost at random - the strip is unfit."""
    cfg = _reader_cfg(axis_speed_mm_per_s=6000.0)
    findings = [f for f in run_rules(ALL_RULES, cfg, derive(cfg)).findings
                if f.rule_id == "SCN-013"]
    assert findings
    assert findings[0].severity is Severity.ERROR
    assert frames_on_a_code(90.0, 6000.0) < 1.0


def test_thin_frame_margin_warns_without_blocking():
    """Two frames wanted, just over two available: real but not fatal."""
    cfg = _reader_cfg(axis_speed_mm_per_s=2400.0, frames_per_code=2, exposure_us=400)
    report = run_rules(ALL_RULES, cfg, derive(cfg))
    scn13 = [f for f in report.findings if f.rule_id == "SCN-013"]
    assert scn13
    assert scn13[0].severity is Severity.WARNING
    assert frames_on_a_code(90.0, 2400.0) > 1.0


def test_a_speed_that_works_does_not_block_the_export():
    cfg = _reader_cfg(axis_speed_mm_per_s=500.0)
    assert not run_rules(ALL_RULES, cfg, derive(cfg)).blocks_export


def test_the_motion_check_needs_no_reader_preset_to_say_something_useful():
    """Exposure and module size alone bound the speed, with no optics at all."""
    cfg = dc.replace(
        AopsConfig(),
        scanner=dc.replace(AopsConfig().scanner, axis_speed_mm_per_s=3000.0),
    )
    assert "SCN-012" in _ids(cfg)
