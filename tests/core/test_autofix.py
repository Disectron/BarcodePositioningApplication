"""The auto-fixer: run every computed correction to a fixed point.

THE CONTRACT
------------
Everything the rules can compute gets applied; everything they cannot comes
back with an honest reason. Three findings are *deliberately* unfixable and
the tests pin that: a strip ID cannot be invented (PRJ-001), a substrate is a
purchasing decision (MED-001), and substituting a different symbology behind
the user's back is worse than refusing (SYM-001) - the placeholder module
says so in as many words.

The other pinned property is monotonicity: a fixer must never make things
worse. Every run ends with no more blocking findings than it started with,
whatever the input.
"""

from __future__ import annotations

import dataclasses as dc

import pytest

from aops.core.autofix import autofix
from aops.core.config import (
    AopsConfig,
    DimensionConfig,
    PayloadConfig,
    PositionConfig,
)
from aops.core.enums import Media, Orientation, Severity, Symbology
from aops.core.rules import ALL_RULES
from aops.core.stats import derive
from aops.core.validation import run_rules


def _report(cfg: AopsConfig):
    try:
        derived = derive(cfg)
    except Exception:
        derived = None
    return run_rules(ALL_RULES, cfg, derived)


A = AopsConfig

#: Broken in every way the rules can repair. Each case must end unblocked.
FIXABLE = {
    "symbol larger than pitch": dc.replace(
        A(), dimensions=DimensionConfig(pitch_mm=25.0, symbol_size_mm=40.0)
    ),
    "quiet zones eat the pitch": dc.replace(
        A(), dimensions=DimensionConfig(pitch_mm=25.0, symbol_size_mm=20.0, quiet_zone_mm=6.0)
    ),
    "pitch zero": dc.replace(A(), dimensions=DimensionConfig(pitch_mm=0.0)),
    "symbol zero": dc.replace(A(), dimensions=DimensionConfig(symbol_size_mm=0.0)),
    "strip height zero": dc.replace(A(), dimensions=DimensionConfig(strip_height_mm=0.0)),
    "negative quiet zone": dc.replace(A(), dimensions=DimensionConfig(quiet_zone_mm=-1.0)),
    "end below start": dc.replace(A(), position=PositionConfig(start_index=10, end_index=5)),
    "increment zero": dc.replace(A(), position=PositionConfig(increment=0)),
    "too few digits": dc.replace(A(), payload=PayloadConfig(digits=2)),
    "scale zero": dc.replace(A(), printing=dc.replace(A().printing, scale_percent=0.0)),
    "scale huge": dc.replace(A(), printing=dc.replace(A().printing, scale_percent=300.0)),
    "calibration length zero": dc.replace(
        A(), printing=dc.replace(A().printing, calibration_length_mm=0.0)
    ),
    "dpi zero": dc.replace(A(), printer=dc.replace(A().printer, dpi=0)),
    "module below three dots": dc.replace(
        A(),
        printer=dc.replace(A().printer, dpi=203),
        dimensions=DimensionConfig(symbol_size_mm=2.0),
    ),
    "portrait clips the calibration bar": dc.replace(
        A(), paper=dc.replace(A().paper, orientation=Orientation.PORTRAIT)
    ),
    "several at once": dc.replace(
        A(),
        dimensions=DimensionConfig(
            pitch_mm=0.0, symbol_size_mm=0.0, strip_height_mm=0.0, quiet_zone_mm=-2.0
        ),
        position=PositionConfig(start_index=5, end_index=1, increment=0),
        payload=PayloadConfig(digits=1),
        printing=dc.replace(A().printing, scale_percent=300.0),
    ),
}


@pytest.mark.parametrize("label", sorted(FIXABLE))
def test_every_repairable_config_ends_unblocked(label):
    result = autofix(FIXABLE[label])
    report = _report(result.config)
    assert not report.blocks_export, [f.message for f in report.blocking]
    assert result.changed


@pytest.mark.parametrize("label", sorted(FIXABLE))
def test_the_fixer_never_makes_things_worse(label):
    """Monotonicity: blocking findings out <= blocking findings in."""
    before = len(_report(FIXABLE[label]).blocking)
    result = autofix(FIXABLE[label])
    assert len(_report(result.config).blocking) <= before


def test_every_step_records_both_sides_of_the_change():
    result = autofix(FIXABLE["symbol larger than pitch"])
    for step in result.steps:
        assert step.before != step.after
        assert "." in step.field
        assert step.label


def test_steps_touch_only_the_fields_they_claim():
    """The final config must differ from the input in exactly the stepped
    fields - a fixer that quietly edits something it never reported would be
    indistinguishable from corruption."""
    cfg = FIXABLE["several at once"]
    result = autofix(cfg)
    claimed = {s.field for s in result.steps}
    for section in ("symbol", "position", "payload", "dimensions", "output",
                    "paper", "printing", "media", "printer", "scanner", "project"):
        a, b = getattr(cfg, section), getattr(result.config, section)
        for field in dc.fields(a):
            path = f"{section}.{field.name}"
            if getattr(a, field.name) != getattr(b, field.name):
                assert path in claimed, f"{path} changed without a step"


def test_a_clean_config_is_left_completely_alone():
    cfg = dc.replace(A(), project=dc.replace(A().project, strip_id="X-AXIS"))
    result = autofix(cfg)
    assert not result.changed
    assert result.config == cfg


def test_fixing_twice_changes_nothing_the_second_time():
    """Idempotence, the cheap way to prove the loop actually converged."""
    once = autofix(FIXABLE["several at once"])
    twice = autofix(once.config)
    assert not twice.changed
    assert twice.config == once.config


# -- what is deliberately left ----------------------------------------------


def test_a_missing_strip_id_is_not_invented():
    result = autofix(A())
    ids = {u.rule_id for u in result.unresolved}
    assert "PRJ-001" in ids
    assert result.config.project.strip_id == ""


def test_a_media_choice_is_not_made_for_the_user():
    cfg = dc.replace(A(), media=dc.replace(A().media, media=Media.PAPER))
    result = autofix(cfg)
    assert result.config.media.media is Media.PAPER
    assert any(u.rule_id == "MED-001" for u in result.unresolved)


def test_a_symbology_is_never_silently_substituted():
    """The placeholder module's whole philosophy, honoured by the fixer too."""
    cfg = dc.replace(A(), symbol=dc.replace(A().symbol, symbology=Symbology.CODE128))
    result = autofix(cfg)
    assert result.config.symbol.symbology is Symbology.CODE128
    assert any(u.rule_id == "SYM-001" for u in result.unresolved)


def test_unresolved_findings_carry_a_usable_reason():
    result = autofix(A())
    for u in result.unresolved:
        assert len(u.reason) > 10, u.rule_id


def test_info_notes_are_not_treated_as_problems():
    """A fixer that "resolves" notes would be optimising the issues list."""
    cfg = dc.replace(A(), project=dc.replace(A().project, strip_id="X-AXIS"))
    report = _report(cfg)
    assert any(f.severity is Severity.INFO for f in report.findings)
    result = autofix(cfg)
    assert not result.changed


def test_the_loop_terminates_on_a_hostile_config():
    """Everything wrong at once must converge, not spin to the round cap."""
    result = autofix(FIXABLE["several at once"])
    assert len(result.steps) < 20
    assert not result.oscillated


# -- the fixes the fixer relies on ------------------------------------------


@pytest.mark.parametrize(
    "label,rule_id",
    [
        ("pitch zero", "GEO-001"),
        ("symbol zero", "GEO-002"),
        ("end below start", "POS-001"),
        ("increment zero", "POS-002"),
        ("scale zero", "PRN-002"),
        ("calibration length zero", "PRN-004"),
        ("dpi zero", "PRN-009"),
        ("module below three dots", "PRN-005"),
        ("portrait clips the calibration bar", "PAG-003"),
    ],
)
def test_each_new_fix_clears_its_own_rule(label: str, rule_id: str):
    """The fixes added for the auto-fixer, each proven to self-clear."""
    finding = next(
        (f for f in _report(FIXABLE[label]).findings if f.rule_id == rule_id), None
    )
    assert finding is not None, f"{rule_id} did not fire for {label}"
    assert finding.fix is not None, f"{rule_id} carries no fix"

    section, name = finding.fix.field.split(".", 1)
    cfg = FIXABLE[label]
    fixed = dc.replace(
        cfg, **{section: dc.replace(getattr(cfg, section), **{name: finding.fix.value})}
    )
    assert rule_id not in {f.rule_id for f in _report(fixed).findings}


def test_the_prn005_fix_lands_on_the_dot_grid():
    """Growing the code to five whole dots must not trade PRN-005 for PRN-010."""
    result = autofix(FIXABLE["module below three dots"])
    ids = {f.rule_id for f in _report(result.config).findings}
    assert "PRN-005" not in ids
    assert "PRN-006" not in ids
    assert "PRN-010" not in ids
