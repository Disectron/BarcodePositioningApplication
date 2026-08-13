"""The solver: from eight facts about the job to a full configuration.

THE PROPERTY THAT MATTERS
-------------------------
Solved configurations must pass the same ~70 validation rules as hand-entered
ones, across the whole grid of speeds, distances and printers. The solver and
the validator implement the same physics independently; agreement between them
is the check. A solver whose output needed its own weaker validation would be
an invitation to trust it, which is exactly backwards.

The other thing defended here is the *reasons*. Every derived value carries a
sentence naming the constraint that decided it, and the tests treat those
sentences as part of the contract - a solver that says "code size 7.5 mm"
without saying the printer demanded it teaches nobody anything and cannot be
argued with.
"""

from __future__ import annotations

import dataclasses as dc

import pytest

from aops.core.config import AopsConfig
from aops.core.motion import EXPOSURE_MIN_US
from aops.core.presets import BUILT_IN_PRESETS
from aops.core.presets import apply as apply_preset
from aops.core.rules import ALL_RULES
from aops.core.solve import (
    COMFORT_EXPOSURE_US,
    DESIGN_MODULE_DOTS,
    PITCH_STEP_MM,
    solve,
)
from aops.core.stats import derive
from aops.core.units import mm_per_dot
from aops.core.validation import run_rules


def job(
    *,
    dpi: int = 203,
    speed: float = 0.0,
    distance: float = 0.0,
    codes_in_view: int = 1,
    reader: bool = True,
) -> AopsConfig:
    """A base configuration describing a job, as the presets would build it."""
    cfg = AopsConfig()
    if reader:
        preset = next(p for p in BUILT_IN_PRESETS if "NVF230" in p.name)
        cfg = apply_preset(preset, cfg)
    return dc.replace(
        cfg,
        printer=dc.replace(cfg.printer, dpi=dpi),
        scanner=dc.replace(
            cfg.scanner,
            axis_speed_mm_per_s=speed,
            mount_distance_mm=distance,
            min_codes_in_view=codes_in_view,
        ),
    )


# -- the property -----------------------------------------------------------


@pytest.mark.parametrize("dpi", [203, 300, 600])
@pytest.mark.parametrize("speed", [0.0, 200.0, 1000.0, 2000.0])
@pytest.mark.parametrize("distance", [0.0, 100.0, 150.0, 200.0])
def test_every_feasible_solution_validates_clean(dpi, speed, distance):
    """The grid: no combination of job inputs may produce a blocked export,
    and a feasible solve must not even produce warnings - a designer that
    hands you a design the checker grumbles about has failed at its one job."""
    solution = solve(job(dpi=dpi, speed=speed, distance=distance), travel_mm=2000.0)
    if not solution.feasible:
        return  # infeasibility is its own honest outcome, tested separately
    report = run_rules(ALL_RULES, solution.config, derive(solution.config))
    assert not report.blocks_export, [f.message for f in report.blocking]
    geometry_warnings = [
        f
        for f in report.findings
        if f.severity >= 1 and f.rule_id.split("-")[0] in ("GEO", "PRN", "SCN", "PAG")
    ]
    assert geometry_warnings == [], [f.message for f in geometry_warnings]


@pytest.mark.parametrize("travel", [100.0, 2000.0, 10_000.0, 50_000.0])
def test_the_travel_is_always_covered(travel):
    solution = solve(job(), travel_mm=travel)
    d = derive(solution.config)
    assert d.max_position_mm >= travel


def test_every_decision_names_its_field_and_reason():
    solution = solve(job(speed=1000.0, distance=150.0), travel_mm=2000.0)
    for decision in solution.decisions:
        assert "." in decision.field
        assert len(decision.reason) > 20, decision.field
    decided = {d.field for d in solution.decisions}
    assert "dimensions.symbol_size_mm" in decided
    assert "dimensions.pitch_mm" in decided
    assert "position.end_index" in decided
    assert "scanner.exposure_us" in decided


# -- the three floors -------------------------------------------------------


def test_the_printer_binds_when_it_is_the_coarsest_constraint():
    """203 dpi, slow, close: five printer dots outweigh everything else."""
    solution = solve(job(dpi=203, speed=200.0, distance=100.0), travel_mm=2000.0)
    symbol = next(d for d in solution.decisions if d.field == "dimensions.symbol_size_mm")
    assert "printer" in symbol.reason
    d = derive(solution.config)
    assert d.cell.module_mm(d.matrix_cols) >= DESIGN_MODULE_DOTS * mm_per_dot(203) - 1e-6


def test_motion_binds_when_the_axis_is_fast():
    """4 m/s at 500 us needs 2 mm modules - more than any printer demands."""
    solution = solve(job(dpi=600, speed=4000.0, distance=200.0), travel_mm=2000.0)
    symbol = next(d for d in solution.decisions if d.field == "dimensions.symbol_size_mm")
    assert "motion" in symbol.reason
    d = derive(solution.config)
    assert d.cell.module_mm(d.matrix_cols) >= 4000.0 * COMFORT_EXPOSURE_US / 1e6 - 1e-6


def test_the_reader_binds_when_mounted_far_away():
    """At 400 mm the NVF230's pixels are spread thin; slow axis, fine printer."""
    solution = solve(job(dpi=600, speed=0.0, distance=400.0), travel_mm=2000.0)
    symbol = next(d for d in solution.decisions if d.field == "dimensions.symbol_size_mm")
    assert "reader" in symbol.reason


def test_the_symbol_lands_on_the_dot_grid():
    """The solver must not hand out the defect its own rule warns about."""
    for dpi in (203, 300, 600):
        solution = solve(job(dpi=dpi), travel_mm=2000.0)
        report = run_rules(ALL_RULES, solution.config, derive(solution.config))
        assert "PRN-010" not in {f.rule_id for f in report.findings}, dpi


# -- derived consequences ---------------------------------------------------


def test_pitch_is_a_clean_multiple():
    solution = solve(job(), travel_mm=2000.0)
    pitch = solution.config.dimensions.pitch_mm
    assert pitch % PITCH_STEP_MM == pytest.approx(0.0)


def test_the_pitch_floor_matches_the_validators_not_something_stricter():
    """Quiet zones count toward the cutting gap, exactly as GEO-013 counts it.

    The first solver added the 3 mm gap on top of the quiet zones and demanded
    a 15 mm pitch where its own validator was happy with 10 - a clumsier
    position formula (P = i x 15) for no safety the checker recognised. The
    reference job must land on the 10 the rules actually permit.
    """
    solution = solve(job(dpi=203, speed=1000.0, distance=150.0), travel_mm=2000.0)
    dims = solution.config.dimensions
    assert dims.pitch_mm == pytest.approx(10.0)

    # And the white gap the rule inspects is at its floor or better.
    assert dims.pitch_mm - dims.symbol_size_mm >= 3.0 - 1e-9

    d = derive(solution.config)
    assert d.position_formula == "P [mm] = Index x 10.000"


def test_the_calibration_bar_spans_the_sheet():
    """The bar is the instrument that measures the printer; the solver makes
    it as long as the paper allows, because length is its accuracy."""
    solution = solve(job(), travel_mm=2000.0)
    assert solution.config.printing.calibration_length_mm == 270.0  # A4 landscape
    bar = next(d for d in solution.decisions
               if d.field == "printing.calibration_length_mm")
    assert "270" in bar.reason
    assert derive(solution.config).accuracy.residual_scale_error == pytest.approx(0.5 / 270.0)


def test_a_disabled_bar_is_not_designed(monkeypatch):
    base = job()
    base = dc.replace(base, output=dc.replace(base.output, calibration_bar=False))
    solution = solve(base, travel_mm=2000.0)
    assert solution.config.printing.calibration_length_mm == base.printing.calibration_length_mm
    assert "printing.calibration_length_mm" not in {d.field for d in solution.decisions}


def test_exposure_keeps_smear_within_one_module():
    solution = solve(job(speed=1500.0, distance=150.0), travel_mm=2000.0)
    cfg = solution.config
    d = derive(cfg)
    smear_mm = 1500.0 * cfg.scanner.exposure_us / 1e6
    assert smear_mm <= d.cell.module_mm(d.matrix_cols) + 1e-6


def test_a_stationary_job_leaves_the_exposure_alone():
    base = job(speed=0.0)
    solution = solve(base, travel_mm=2000.0)
    assert solution.config.scanner.exposure_us == base.scanner.exposure_us
    assert "scanner.exposure_us" not in {d.field for d in solution.decisions}


def test_digits_cover_the_largest_position():
    solution = solve(job(), travel_mm=9999.0)
    d = derive(solution.config)
    assert 10 ** solution.config.payload.digits > d.max_position_mm


def test_identity_and_media_pass_through_untouched():
    """The solver designs geometry; it must not touch who the strip is for."""
    base = job()
    base = dc.replace(
        base,
        project=dc.replace(base.project, machine="LATHE-04", strip_id="X-AXIS"),
    )
    solution = solve(base, travel_mm=2000.0)
    assert solution.config.project == base.project
    assert solution.config.media == base.media
    assert solution.config.output == base.output


# -- honest infeasibility ---------------------------------------------------


def test_an_impossible_speed_is_reported_not_papered_over():
    """40 m/s: the exposure needed is far below the reader's floor."""
    solution = solve(job(dpi=203, speed=40_000.0, distance=100.0), travel_mm=2000.0)
    # The motion floor sizes the module up so far that the code cannot fit the
    # window, or the exposure clamps at the floor - either way, problems.
    assert not solution.feasible
    assert solution.config.scanner.exposure_us >= EXPOSURE_MIN_US


def test_too_much_redundancy_for_the_window_is_reported():
    """Three codes in view through a close-mounted reader cannot fit.

    At 35 mm the NVF230 sees ~31.5 mm; three 10 mm pitches plus a code is
    ~36.3. (This distance moved once already: aligning the pitch floor with
    GEO-013 dropped the reference pitch from 15 to 10 mm, which made the old
    50 mm scenario legitimately feasible - the solver improving is allowed to
    invalidate the test's scenario, not its property.)
    """
    solution = solve(
        job(dpi=203, distance=35.0, codes_in_view=3), travel_mm=2000.0
    )
    assert not solution.feasible
    assert any("in view" in p for p in solution.problems)


def test_infeasibility_matches_the_validators_verdict():
    """When the solver says 'cannot', the rules must agree something is wrong -
    the two are independent implementations of the same physics."""
    solution = solve(
        job(dpi=203, distance=35.0, codes_in_view=3), travel_mm=2000.0
    )
    report = run_rules(ALL_RULES, solution.config, derive(solution.config))
    assert report.max_severity >= 1


def test_no_reader_and_no_speed_still_designs_a_printable_strip():
    """With only a printer stated, the print floors alone produce a clean strip."""
    solution = solve(job(reader=False), travel_mm=2000.0)
    assert solution.feasible
    report = run_rules(ALL_RULES, solution.config, derive(solution.config))
    assert not report.blocks_export
