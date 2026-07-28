"""Reusable configuration presets.

The property that matters most is what a preset *refuses* to carry. A preset
is "how we build strips here"; the machine name, strip ID, revision and index
range are "which strip is this". If applying a house standard also stamped the
new job with the old machine's identity, the mistake would be silent right up
until it reached a printed sheet - so most of these tests are about the things
that must survive an apply untouched.
"""

from __future__ import annotations

import dataclasses as dc

import pytest

from aops.core.config import (
    CONFIG_SECTIONS,
    AopsConfig,
    DimensionConfig,
    MediaConfig,
    PositionConfig,
    PrinterConfig,
    ProjectConfig,
)
from aops.core.enums import Media, PaperPreset
from aops.core.errors import ProjectFileError
from aops.core.presets import (
    BUILT_IN_PRESETS,
    PER_STRIP_FIELDS,
    Preset,
    apply,
    capture,
    dump_preset,
    load_preset,
)
from aops.core.rules import ALL_RULES
from aops.core.stats import derive
from aops.core.validation import run_rules

HOUSE = dc.replace(
    AopsConfig(),
    dimensions=DimensionConfig(pitch_mm=30.0, symbol_size_mm=12.0),
    media=MediaConfig(media=Media.VINYL),
    printer=PrinterConfig(dpi=300),
    position=PositionConfig(start_index=0, end_index=99, origin_mm=500.0),
    project=ProjectConfig(
        machine="GANTRY-01", strip_id="AX1-POS-001", revision="C", engineer="R. Kelly"
    ),
)

OTHER = dc.replace(
    AopsConfig(),
    position=PositionConfig(start_index=0, end_index=420, origin_mm=0.0),
    project=ProjectConfig(machine="LATHE-07", strip_id="AX9-POS-002", revision="A"),
)


# -- what a preset carries --------------------------------------------------


def test_a_preset_carries_the_reusable_settings():
    out = apply(capture(HOUSE, "house"), OTHER)
    assert out.dimensions.pitch_mm == 30.0
    assert out.dimensions.symbol_size_mm == 12.0
    assert out.media.media is Media.VINYL
    assert out.printer.dpi == 300


def test_a_preset_never_carries_the_strip_identity():
    """The whole point. Applying must not rewrite which strip this is."""
    out = apply(capture(HOUSE, "house"), OTHER)
    assert out.project.machine == "LATHE-07"
    assert out.project.strip_id == "AX9-POS-002"
    assert out.project.revision == "A"


def test_a_preset_never_carries_the_index_range_or_origin():
    out = apply(capture(HOUSE, "house"), OTHER)
    assert out.position.end_index == 420
    assert out.position.origin_mm == 0.0


def test_the_engineer_and_company_do_travel():
    """House details, not strip details - repeating them every time is the chore."""
    assert apply(capture(HOUSE, "house"), OTHER).project.engineer == "R. Kelly"


def test_house_convention_fields_travel():
    """Increment, pitch mode, direction and datum are convention, not identity."""
    source = dc.replace(
        HOUSE, position=dc.replace(HOUSE.position, increment=2)
    )
    assert apply(capture(source, "house"), OTHER).position.increment == 2


def test_capture_excludes_exactly_the_declared_fields():
    captured = {
        f"{section}.{field}" for section, fields in capture(HOUSE, "x").values for field, _v in fields
    }
    assert not (captured & PER_STRIP_FIELDS)


def test_capture_covers_every_other_field():
    """A field missing from a preset silently fails to be reused."""
    captured = {
        f"{section}.{field}" for section, fields in capture(HOUSE, "x").values for field, _v in fields
    }
    everything = {
        f"{name}.{f.name}"
        for name in CONFIG_SECTIONS
        for f in dc.fields(getattr(AopsConfig(), name))
    }
    assert everything - captured == PER_STRIP_FIELDS


def test_every_excluded_field_actually_exists():
    """A typo in the exclusion set would silently leak an identity field."""
    for path in PER_STRIP_FIELDS:
        section, _, field = path.partition(".")
        assert hasattr(getattr(AopsConfig(), section), field), path


# -- persistence ------------------------------------------------------------


def test_round_trip_through_json_is_lossless():
    preset = capture(HOUSE, "house", "our standard")
    restored = load_preset(dump_preset(preset, app_version="test"))
    assert restored.name == "house"
    assert restored.description == "our standard"
    assert apply(restored, OTHER) == apply(preset, OTHER)


def test_applying_twice_changes_nothing_further():
    preset = capture(HOUSE, "house")
    once = apply(preset, OTHER)
    assert apply(preset, once) == once


def test_rejects_a_file_that_is_not_a_preset():
    with pytest.raises(ProjectFileError):
        load_preset('{"format": "aops-project", "schema_version": 1}')


def test_rejects_malformed_json():
    with pytest.raises(ProjectFileError):
        load_preset("{not json")


def test_rejects_a_newer_schema_rather_than_guessing():
    with pytest.raises(ProjectFileError):
        load_preset('{"format": "aops-preset", "schema_version": 99, "values": {}}')


# -- robustness -------------------------------------------------------------


def test_unknown_sections_and_fields_are_skipped_not_fatal():
    """A preset from a newer build should apply what this one understands."""
    preset = Preset(
        name="from the future",
        values=(
            ("dimensions", (("pitch_mm", 40.0), ("warp_factor", 9))),
            ("hyperdrive", (("enabled", True),)),
        ),
    )
    out = apply(preset, OTHER)
    assert out.dimensions.pitch_mm == 40.0


def test_an_identity_field_smuggled_into_a_preset_is_still_refused():
    """Belt and braces: apply filters too, not only capture."""
    preset = Preset(
        name="malicious",
        values=(("project", (("machine", "WRONG"),)), ("position", (("end_index", 7),))),
    )
    out = apply(preset, OTHER)
    assert out.project.machine == "LATHE-07"
    assert out.position.end_index == 420


def test_an_empty_preset_is_harmless():
    assert apply(Preset(name="empty"), OTHER) == OTHER


# -- the shipped presets ----------------------------------------------------


@pytest.mark.parametrize("preset", BUILT_IN_PRESETS, ids=lambda p: p.name)
def test_built_in_presets_apply_cleanly(preset: Preset):
    out = apply(preset, AopsConfig())
    assert derive(out).code_count > 0


@pytest.mark.parametrize("preset", BUILT_IN_PRESETS, ids=lambda p: p.name)
def test_built_in_presets_do_not_block_export(preset: Preset):
    cfg = apply(preset, AopsConfig())
    blocking = run_rules(ALL_RULES, cfg, derive(cfg)).blocking
    assert not blocking, [f"{f.rule_id}: {f.message}" for f in blocking]


@pytest.mark.parametrize("preset", BUILT_IN_PRESETS, ids=lambda p: p.name)
def test_built_in_presets_round_trip(preset: Preset):
    restored = load_preset(dump_preset(preset, app_version="test"))
    assert apply(restored, AopsConfig()) == apply(preset, AopsConfig())


@pytest.mark.parametrize("preset", BUILT_IN_PRESETS, ids=lambda p: p.name)
def test_built_in_presets_are_described(preset: Preset):
    assert preset.name and preset.description
    assert preset.field_count > 0


def test_built_in_presets_have_distinct_names():
    names = [p.name for p in BUILT_IN_PRESETS]
    assert len(set(names)) == len(names)


def test_the_roll_preset_selects_roll_media_and_continuous_output():
    """It exists to encode one recommendation; check it actually does."""
    roll = next(p for p in BUILT_IN_PRESETS if "roll" in p.name.lower())
    out = apply(roll, AopsConfig())
    assert out.paper.preset.is_roll
    assert out.output.continuous and not out.output.tiled_pages
    assert out.printer.unprintable_margin_mm == 0.0


def test_the_roll_preset_avoids_the_band_stack_trap():
    """A 4in roll at default margins clips. The preset must not ship that."""
    out = apply(next(p for p in BUILT_IN_PRESETS if "roll" in p.name.lower()), AopsConfig())
    findings = run_rules(ALL_RULES, out, derive(out)).findings
    assert not [f for f in findings if f.rule_id == "PAG-010"]


def test_the_fine_pitch_preset_keeps_the_payload_representable():
    """12.5 mm steps cannot be encoded in whole millimetres."""
    fine = next(p for p in BUILT_IN_PRESETS if "fine" in p.name.lower())
    out = apply(fine, AopsConfig())
    assert out.dimensions.pitch_mm == 12.5
    assert derive(out).precision_loss_mm == pytest.approx(0.0)


def test_presets_do_not_disturb_the_paper_preset_unless_they_set_it():
    fine = next(p for p in BUILT_IN_PRESETS if "fine" in p.name.lower())
    start = dc.replace(AopsConfig(), paper=dc.replace(AopsConfig().paper, preset=PaperPreset.A3))
    assert apply(fine, start).paper.preset is PaperPreset.A3
