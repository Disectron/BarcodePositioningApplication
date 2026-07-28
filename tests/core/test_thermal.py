"""Thermal expansion - the larger of the two environmental terms.

The tool reported humidity prominently from the start and said nothing about
temperature, which for polyester moves the strip roughly twelve times further.
These tests pin down the physics, the sign convention and the mounting
behaviour, because all three are easy to get subtly wrong and none of them
announce themselves on a printed page.
"""

from __future__ import annotations

import dataclasses as dc

import pytest

from aops.core.config import AopsConfig, MediaConfig
from aops.core.enums import FrameMaterial, Media, Severity, TapeMounting
from aops.core.media import (
    bond_strain_ppm,
    thermal_differential_mm,
    thermal_drift_mm,
    thermal_free_mm,
)
from aops.core.rules import ALL_RULES
from aops.core.stats import derive
from aops.core.validation import run_rules

STRIP_MM = 10_000.0


def cfg_with(**kwargs) -> AopsConfig:
    return dc.replace(AopsConfig(), media=MediaConfig(**kwargs))


def findings(cfg: AopsConfig, rule_id: str):
    report = run_rules(ALL_RULES, cfg, derive(cfg))
    return [f for f in report.findings if f.rule_id == rule_id]


# -- the arithmetic ---------------------------------------------------------


def test_free_expansion_is_length_times_cte_times_swing():
    """Polyester at 17 ppm over 10 m and 30 C is 5.1 mm."""
    media = MediaConfig(media=Media.POLYESTER, temp_swing_deg_c=30.0)
    assert thermal_free_mm(media, STRIP_MM) == pytest.approx(10_000.0 * 17e-6 * 30.0)
    assert thermal_free_mm(media, STRIP_MM) == pytest.approx(5.1, abs=0.01)


def test_only_the_frame_differential_reaches_the_reading():
    """Polyester (17) on steel (12) leaves 5 ppm, not the full 17."""
    media = MediaConfig(
        media=Media.POLYESTER,
        frame_material=FrameMaterial.STEEL,
        temp_swing_deg_c=30.0,
    )
    assert media.cte_mismatch_ppm_per_c == pytest.approx(5.0)
    assert thermal_differential_mm(media, STRIP_MM) == pytest.approx(1.5, abs=0.01)


def test_differential_changes_sign_on_aluminium():
    """Aluminium (23) outruns polyester (17), so the error reverses direction.

    The sign is the whole reason the differential is reported signed: an
    engineer compensating in the wrong direction doubles the error.
    """
    steel = MediaConfig(frame_material=FrameMaterial.STEEL)
    alu = MediaConfig(frame_material=FrameMaterial.ALUMINIUM)
    assert thermal_differential_mm(steel, STRIP_MM) > 0.0
    assert thermal_differential_mm(alu, STRIP_MM) < 0.0


def test_granite_gives_the_largest_differential_of_the_frames():
    """Granite barely moves, so the tape's own expansion is almost all error."""
    worst = max(
        FrameMaterial,
        key=lambda f: abs(thermal_differential_mm(MediaConfig(frame_material=f), STRIP_MM)),
    )
    assert worst is FrameMaterial.GRANITE


def test_zero_swing_produces_no_thermal_term():
    media = MediaConfig(temp_swing_deg_c=0.0, mounting=TapeMounting.END_ANCHORED)
    assert thermal_free_mm(media, STRIP_MM) == 0.0
    assert thermal_drift_mm(media, STRIP_MM) == 0.0


def test_thermal_scales_linearly_with_length_and_swing():
    base = MediaConfig(mounting=TapeMounting.END_ANCHORED, temp_swing_deg_c=10.0)
    triple = MediaConfig(mounting=TapeMounting.END_ANCHORED, temp_swing_deg_c=30.0)
    assert thermal_drift_mm(triple, STRIP_MM) == pytest.approx(
        3.0 * thermal_drift_mm(base, STRIP_MM)
    )
    assert thermal_drift_mm(base, 2 * STRIP_MM) == pytest.approx(
        2.0 * thermal_drift_mm(base, STRIP_MM)
    )


# -- mounting ---------------------------------------------------------------


def test_bonding_cancels_the_reading_error_and_moves_it_into_the_adhesive():
    """The strain does not vanish; it is carried somewhere else."""
    bonded = MediaConfig(mounting=TapeMounting.CONTINUOUS_BOND)
    assert thermal_drift_mm(bonded, STRIP_MM) == 0.0
    assert bond_strain_ppm(bonded) > 0.0


def test_end_anchored_takes_the_full_differential_and_loads_no_adhesive():
    free = MediaConfig(mounting=TapeMounting.END_ANCHORED)
    assert thermal_drift_mm(free, STRIP_MM) == pytest.approx(
        abs(thermal_differential_mm(free, STRIP_MM))
    )
    assert bond_strain_ppm(free) == 0.0


def test_drift_is_unsigned_but_differential_keeps_its_sign():
    """Callers comparing against a tolerance want a magnitude."""
    alu = MediaConfig(mounting=TapeMounting.END_ANCHORED, frame_material=FrameMaterial.ALUMINIUM)
    assert thermal_differential_mm(alu, STRIP_MM) < 0.0
    assert thermal_drift_mm(alu, STRIP_MM) > 0.0


# -- how it reads against the humidity term ---------------------------------


def test_temperature_beats_humidity_on_polyester():
    """The finding that motivated all of this."""
    cfg = cfg_with(mounting=TapeMounting.END_ANCHORED)
    acc = derive(cfg).accuracy
    assert acc.thermal_drift_mm > acc.media_drift_mm
    assert acc.thermal_dominates


def test_humidity_still_dominates_on_paper():
    """Paper is a humidity problem, and the model must not overstate thermal."""
    cfg = cfg_with(media=Media.PAPER, mounting=TapeMounting.END_ANCHORED)
    acc = derive(cfg).accuracy
    assert acc.media_drift_mm > acc.thermal_drift_mm
    assert not acc.thermal_dominates


def test_combined_drift_is_quadrature_not_a_sum():
    cfg = cfg_with(mounting=TapeMounting.END_ANCHORED)
    acc = derive(cfg).accuracy
    combined = acc.environmental_drift_mm
    assert combined < acc.media_drift_mm + acc.thermal_drift_mm
    assert combined >= max(acc.media_drift_mm, acc.thermal_drift_mm)


# -- validation -------------------------------------------------------------


def test_large_thermal_drift_warns():
    cfg = cfg_with(mounting=TapeMounting.END_ANCHORED, media=Media.VINYL, temp_swing_deg_c=40.0)
    assert findings(cfg, "MED-006")


def test_thermal_beyond_half_a_pitch_is_an_error():
    """Past half a pitch the reader can land on the wrong code entirely."""
    cfg = cfg_with(
        mounting=TapeMounting.END_ANCHORED,
        media=Media.VINYL,
        frame_material=FrameMaterial.GRANITE,
        temp_swing_deg_c=60.0,
    )
    found = findings(cfg, "MED-006")
    assert found and found[0].severity is Severity.ERROR


def test_bonding_a_mismatched_substrate_warns_about_the_adhesive():
    cfg = cfg_with(media=Media.VINYL, frame_material=FrameMaterial.GRANITE)
    assert findings(cfg, "MED-008")


def test_well_matched_bonded_strip_raises_nothing():
    """Polyester bonded to stainless is a genuinely good combination (0 ppm)."""
    cfg = cfg_with(media=Media.POLYESTER, frame_material=FrameMaterial.STAINLESS)
    assert not findings(cfg, "MED-006")
    assert not findings(cfg, "MED-008")


# -- overrides --------------------------------------------------------------


def test_cte_override_replaces_the_published_figure():
    media = MediaConfig(cte_ppm_per_c=100.0)
    assert media.effective_cte_ppm_per_c == 100.0


def test_zero_cte_override_falls_back_to_the_media_figure():
    media = MediaConfig(media=Media.POLYESTER, cte_ppm_per_c=0.0)
    assert media.effective_cte_ppm_per_c == Media.POLYESTER.cte_ppm_per_c


def test_every_media_and_frame_declares_a_cte():
    """A missing entry would KeyError at report time rather than at import."""
    for member in Media:
        assert member.cte_ppm_per_c > 0.0
    for member in FrameMaterial:
        assert member.cte_ppm_per_c > 0.0
        assert member.display_name
