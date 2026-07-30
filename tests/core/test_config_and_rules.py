"""Configuration model, project I/O, positions, payloads and validation rules."""

from __future__ import annotations

import dataclasses as dc

import pytest

from aops import __version__
from aops.core.cell import resolve_cell
from aops.core.config import (
    CONFIG_SECTIONS,
    AopsConfig,
    DimensionConfig,
    PayloadConfig,
    PositionConfig,
)
from aops.core.enums import Direction, Media, Orientation, PitchMode, Severity, Symbology
from aops.core.errors import ProjectFileError
from aops.core.payload import payload_for, precision_loss_mm, required_digits
from aops.core.positions import code_count, code_indices, position_formula, position_mm
from aops.core.project_io import (
    CURRENT_SCHEMA_VERSION,
    config_fingerprint,
    dump_project,
    load_project,
)
from aops.core.rules import ALL_RULES
from aops.core.stats import derive
from aops.core.validation import run_rules

#: Absolute units, plus the ratio forms ("percent per %RH", "pixels per module")
#: that are just as self-describing.
KNOWN_SUFFIXES = (
    "_mm",
    "_pt",
    "_percent",
    "_deg",
    "_dpi",
    "_pct_per_rh",
    "_per_module",
    "_deg_c",
    "_ppm_per_c",
)


# -- config model -----------------------------------------------------------


def test_every_float_field_carries_a_unit_suffix():
    """Enforced by test rather than by convention alone."""
    offenders: list[str] = []
    for section_name in CONFIG_SECTIONS:
        section = getattr(AopsConfig(), section_name)
        for field in dc.fields(section):
            annotation = str(field.type)
            if "float" not in annotation or "tuple" in annotation:
                continue
            if not field.name.endswith(KNOWN_SUFFIXES):
                offenders.append(f"{section_name}.{field.name}")
    assert offenders == [], f"float fields without a unit suffix: {offenders}"


def test_config_is_hashable_and_frozen():
    cfg = AopsConfig()
    assert hash(cfg) == hash(AopsConfig())
    with pytest.raises(dc.FrozenInstanceError):
        cfg.dimensions.pitch_mm = 30.0  # type: ignore[misc]


# -- project I/O ------------------------------------------------------------


def test_project_round_trip_is_lossless():
    cfg = dc.replace(
        AopsConfig(),
        dimensions=DimensionConfig(pitch_mm=32.5, symbol_size_mm=12.0),
        position=PositionConfig(start_index=10, end_index=200, increment=2),
    )
    loaded = load_project(dump_project(cfg, app_version=__version__))
    assert loaded.config == cfg
    assert loaded.schema_version == CURRENT_SCHEMA_VERSION


def test_future_schema_is_refused_not_guessed():
    text = dump_project(AopsConfig(), app_version=__version__)
    text = text.replace(
        f'"schema_version": {CURRENT_SCHEMA_VERSION}', '"schema_version": 99'
    )
    with pytest.raises(ProjectFileError, match="schema 99"):
        load_project(text)


def test_unknown_keys_are_preserved():
    text = dump_project(AopsConfig(), app_version=__version__)
    text = text.replace("{\n", '{\n  "future_field": "keep me",\n', 1)
    loaded = load_project(text)
    assert any(key == "future_field" for key, _ in loaded.config.extra)
    assert "future_field" in dump_project(loaded.config, app_version=__version__)


def test_fingerprint_changes_with_geometry_but_not_with_extra():
    a = AopsConfig()
    b = dc.replace(a, dimensions=dc.replace(a.dimensions, pitch_mm=30.0))
    assert config_fingerprint(a) != config_fingerprint(b)
    c = dc.replace(a, extra=(("x", "1"),))
    assert config_fingerprint(a) == config_fingerprint(c)


def test_non_aops_file_is_rejected():
    with pytest.raises(ProjectFileError):
        load_project('{"format": "something-else", "schema_version": 1}')


# -- positions and payloads -------------------------------------------------


def test_position_formula_cases():
    cell = resolve_cell(DimensionConfig())
    assert position_formula(PositionConfig(), cell) == "P [mm] = Index x 25.000"

    offset = PositionConfig(start_index=100, end_index=200, origin_mm=250.0)
    assert position_formula(offset, cell) == "P [mm] = (Index - 100) x 25.000 + 250.000"

    stepped = PositionConfig(start_index=0, end_index=10, increment=2)
    assert position_formula(stepped, cell) == "P [mm] = ((Index - 0) / 2) x 25.000"

    reverse = PositionConfig(start_index=0, end_index=420, direction=Direction.REVERSE)
    assert position_formula(reverse, cell).startswith("P [mm] = 10500.000 - Index x 25.000")


def test_pitch_modes_differ_when_increment_is_not_one():
    """The distinction that keeps a PLC from driving to the wrong place."""
    cell = resolve_cell(DimensionConfig())
    per_cell = PositionConfig(start_index=0, end_index=9, increment=3,
                              pitch_mode=PitchMode.PER_CELL)
    per_index = dc.replace(per_cell, pitch_mode=PitchMode.PER_INDEX)
    assert position_mm(6, per_cell, cell) == 50.0
    assert position_mm(6, per_index, cell) == 150.0


def test_code_count_and_indices_agree():
    pos = PositionConfig(start_index=5, end_index=25, increment=4)
    assert code_count(pos) == len(code_indices(pos)) == 6
    assert code_indices(pos) == (5, 9, 13, 17, 21, 25)


def test_payload_encodes_absolute_millimetres():
    cell = resolve_cell(DimensionConfig())
    pos, pay = PositionConfig(), PayloadConfig(digits=6)
    assert payload_for(0, pos, cell, pay) == "000000"
    assert payload_for(1, pos, cell, pay) == "000025"
    assert payload_for(420, pos, cell, pay) == "010500"


def test_required_digits_uses_position_not_index():
    cell = resolve_cell(DimensionConfig())
    # 420 indices, but the largest position is 10500 -> five digits.
    assert required_digits(PositionConfig(), cell, PayloadConfig()) == 5


def test_fractional_pitch_precision_loss_is_reported():
    cell = resolve_cell(DimensionConfig(pitch_mm=12.5, symbol_size_mm=8.0))
    loss = precision_loss_mm(PositionConfig(end_index=10), cell, PayloadConfig(unit_scale=1))
    assert loss == pytest.approx(0.5)
    # Tenths of a millimetre represent it exactly.
    assert precision_loss_mm(
        PositionConfig(end_index=10), cell, PayloadConfig(unit_scale=10)
    ) == pytest.approx(0.0)


# -- validation rules -------------------------------------------------------


def _report(cfg: AopsConfig):
    try:
        derived = derive(cfg)
    except Exception:
        derived = None
    return run_rules(ALL_RULES, cfg, derived)


def _ids(report) -> set[str]:
    return {f.rule_id for f in report.findings}


def test_default_configuration_does_not_block_export():
    report = _report(AopsConfig())
    assert not report.blocks_export, [f.message for f in report.blocking]


@pytest.mark.parametrize(
    "rule_id,cfg",
    [
        ("GEO-003", dc.replace(AopsConfig(), dimensions=DimensionConfig(symbol_size_mm=30.0))),
        ("GEO-004", dc.replace(AopsConfig(), dimensions=DimensionConfig(quiet_zone_mm=8.0))),
        ("POS-001", dc.replace(AopsConfig(), position=PositionConfig(start_index=10, end_index=5))),
        ("PAY-001", dc.replace(AopsConfig(), payload=PayloadConfig(digits=2))),
        ("SYM-001", dc.replace(AopsConfig(),
                               symbol=dc.replace(AopsConfig().symbol, symbology=Symbology.CODE128))),
        ("MED-001", dc.replace(AopsConfig(), media=dc.replace(AopsConfig().media, media=Media.PAPER))),
        ("PAG-003", dc.replace(AopsConfig(),
                               paper=dc.replace(AopsConfig().paper, orientation=Orientation.PORTRAIT))),
        ("PRN-002", dc.replace(AopsConfig(),
                               printing=dc.replace(AopsConfig().printing, scale_percent=0.0))),
    ],
)
def test_rule_fires_and_blocks(rule_id: str, cfg: AopsConfig):
    report = _report(cfg)
    assert rule_id in _ids(report), f"{rule_id} did not fire"
    assert report.blocks_export


def test_rules_are_silent_when_they_should_be():
    report = _report(AopsConfig())
    for rule_id in ("GEO-003", "GEO-004", "POS-001", "PAY-001", "SYM-001", "MED-001"):
        assert rule_id not in _ids(report)


def test_module_size_in_dots_blocks_at_low_dpi():
    cfg = dc.replace(
        AopsConfig(),
        printer=dc.replace(AopsConfig().printer, dpi=203),
        dimensions=DimensionConfig(symbol_size_mm=2.0, pitch_mm=25.0),
    )
    report = _report(cfg)
    assert "PRN-005" in _ids(report)
    assert report.blocks_export


def test_scanner_fov_is_reported():
    report = _report(AopsConfig())
    fov = next(f for f in report.findings if f.rule_id == "SCN-001")
    assert "35.0 mm" in fov.message


def test_redundancy_raises_required_fov():
    cfg = dc.replace(AopsConfig(), scanner=dc.replace(AopsConfig().scanner, min_codes_in_view=3))
    derived = derive(cfg)
    assert derived.scanner.fov_continuous_mm == pytest.approx(85.0)
    assert derived.scanner.occlusion_tolerance_mm == pytest.approx(50.0)


def test_severity_ordering_and_blocking():
    report = _report(dc.replace(AopsConfig(), payload=PayloadConfig(digits=1)))
    assert report.max_severity >= Severity.ERROR
    assert report.sorted()[0].severity == report.max_severity


# -- axis travel, the number an engineer actually has -----------------------


def test_travel_and_end_index_are_inverses():
    from aops.core.positions import end_index_for_travel, travel_mm

    cell = resolve_cell(DimensionConfig(pitch_mm=25.0, symbol_size_mm=10.0))
    for end in (1, 5, 42, 420):
        pos = PositionConfig(start_index=0, end_index=end)
        assert end_index_for_travel(travel_mm(pos, cell), pos, cell) == end


@pytest.mark.parametrize("travel", [1.0, 499.0, 500.0, 2000.0, 2010.0, 10500.0])
def test_the_range_always_covers_the_travel_asked_for(travel: float):
    """Rounded up on purpose: stopping short leaves the axis end uncoded."""
    import dataclasses as dcl

    from aops.core.positions import end_index_for_travel, travel_mm

    cell = resolve_cell(DimensionConfig(pitch_mm=25.0, symbol_size_mm=10.0))
    pos = PositionConfig(start_index=0, end_index=0)
    fitted = dcl.replace(pos, end_index=end_index_for_travel(travel, pos, cell))
    assert travel_mm(fitted, cell) >= travel


def test_a_travel_of_zero_or_less_asks_for_no_codes():
    from aops.core.positions import end_index_for_travel

    cell = resolve_cell(DimensionConfig(pitch_mm=25.0, symbol_size_mm=10.0))
    pos = PositionConfig(start_index=7, end_index=0)
    for travel in (0.0, -100.0):
        assert end_index_for_travel(travel, pos, cell) == 7


def test_travel_respects_a_non_zero_start_index():
    import dataclasses as dcl

    from aops.core.positions import end_index_for_travel, travel_mm

    cell = resolve_cell(DimensionConfig(pitch_mm=25.0, symbol_size_mm=10.0))
    pos = PositionConfig(start_index=100, end_index=100)
    end = end_index_for_travel(1000.0, pos, cell)
    assert travel_mm(dcl.replace(pos, end_index=end), cell) >= 1000.0


def test_a_single_code_spans_no_travel():
    from aops.core.positions import travel_mm

    cell = resolve_cell(DimensionConfig(pitch_mm=25.0, symbol_size_mm=10.0))
    assert travel_mm(PositionConfig(start_index=0, end_index=0), cell) == 0.0
