"""Simple and Advanced configuration modes.

Eighty-six settings is the right number to get an industrial strip physically
correct and the wrong number to put in front of a first-time user. Simple mode
shows seventeen.

THE PROPERTY THAT MATTERS IS CLOSURE
------------------------------------
Every validation error a Simple-mode user can cause, they must be able to clear
without knowing Advanced mode exists. A mode that lets you break the geometry
and then hides the field that fixes it is a worse trap than the full panel,
because the way out is invisible. Most of this file is about that.
"""

from __future__ import annotations

import dataclasses as dc
import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from aops.core.config import (  # noqa: E402
    AopsConfig,
    DimensionConfig,
    PayloadConfig,
    PositionConfig,
)
from aops.core.enums import Severity  # noqa: E402
from aops.core.rules import ALL_RULES  # noqa: E402
from aops.core.stats import derive  # noqa: E402
from aops.core.validation import run_rules  # noqa: E402
from aops.resources.field_levels import (  # noqa: E402
    JOB_BAR_FIELDS,
    REACHABLE_IN_SIMPLE,
    SIMPLE_FIELDS,
    UiLevel,
    level_for,
    visible_at,
)


@pytest.fixture(scope="module")
def app():
    from aops.app import create_app

    yield QApplication.instance() or create_app([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    """A window whose preferences live in this test, not in the real QSettings.

    The mode is persisted, so reading it back from the machine's own settings
    file would make these tests depend on whatever the developer last clicked -
    and writing to it would leave the application in whichever mode the suite
    finished in. Both directions are stubbed onto a local dict, which also makes
    the round-trip test test the mechanism rather than the disk.
    """
    from aops.ui.main_window import MainWindow
    from aops.ui.settings_store import SettingsStore

    stored = {"mode": UiLevel.ADVANCED.name}
    monkeypatch.setattr(SettingsStore, "presets_dir", lambda self: tmp_path)
    monkeypatch.setattr(SettingsStore, "ui_mode", lambda self: stored["mode"])
    monkeypatch.setattr(
        SettingsStore, "set_ui_mode", lambda self, name: stored.__setitem__("mode", name)
    )
    win = MainWindow()
    yield win
    win._store.mark_saved()
    win.close()


def not_hidden(win) -> int:
    return sum(1 for p in win._panels.values() for r in p.rows().values() if not r.isHidden())


# -- the closure property ---------------------------------------------------


def errors_for(cfg: AopsConfig):
    try:
        derived = derive(cfg)
    except Exception:
        derived = None
    return [
        f
        for f in run_rules(ALL_RULES, cfg, derived).findings
        if f.severity >= Severity.ERROR
    ]


SIMPLE_MISTAKES = {
    "code larger than the spacing": dc.replace(
        AopsConfig(), dimensions=DimensionConfig(pitch_mm=25.0, symbol_size_mm=40.0)
    ),
    "code taller than the band": dc.replace(
        AopsConfig(),
        dimensions=DimensionConfig(pitch_mm=60.0, symbol_size_mm=40.0, strip_height_mm=15.0),
    ),
    "clear border eats the spacing": dc.replace(
        AopsConfig(),
        dimensions=DimensionConfig(pitch_mm=25.0, symbol_size_mm=20.0, quiet_zone_mm=6.0),
    ),
    "spacing tiny": dc.replace(
        AopsConfig(), dimensions=DimensionConfig(pitch_mm=0.5, symbol_size_mm=10.0)
    ),
    "no codes at all": dc.replace(
        AopsConfig(), position=PositionConfig(start_index=0, end_index=-1)
    ),
}


@pytest.mark.parametrize("label", sorted(SIMPLE_MISTAKES))
def test_every_simple_mistake_is_fixable_in_simple_mode(label):
    """The closure property, walked over mistakes Simple mode permits.

    An error is clearable if the control it points at is reachable in Simple -
    an accordion row Simple shows, or a job-bar field on screen in both modes -
    or if it carries a one-click Fix. The Issues list is visible in both modes,
    and activating a finding switches to Advanced on the user's behalf.
    """
    unreachable = []
    for finding in errors_for(SIMPLE_MISTAKES[label]):
        reachable = (
            finding.field in REACHABLE_IN_SIMPLE
            or finding.fix is not None
            or finding.field is None
        )
        if not reachable:
            unreachable.append(f"{finding.rule_id} points at {finding.field}")
    assert unreachable == [], f"{label}: no way out in Simple mode: {unreachable}"


def test_a_simple_user_can_reach_a_valid_exportable_strip():
    """With only Simple fields touched, the defaults must still export."""
    cfg = dc.replace(
        AopsConfig(),
        dimensions=DimensionConfig(pitch_mm=55.0, symbol_size_mm=40.0,
                                   quiet_zone_mm=4.0, strip_height_mm=60.0),
        position=PositionConfig(start_index=0, end_index=37),
    )
    assert not run_rules(ALL_RULES, cfg, derive(cfg)).blocks_export


def test_the_payload_digit_error_carries_its_own_fix():
    """digits is Advanced, so PAY-001 must be self-clearing or it is a trap."""
    cfg = dc.replace(AopsConfig(), payload=PayloadConfig(digits=2))
    found = [f for f in errors_for(cfg) if f.rule_id == "PAY-001"]
    assert found
    assert level_for("payload.digits") is UiLevel.ADVANCED
    assert found[0].fix is not None


# -- what each mode shows ---------------------------------------------------


def test_simple_shows_the_declared_set_and_advanced_shows_everything(window):
    window._set_mode(UiLevel.SIMPLE)
    simple = not_hidden(window)
    window._set_mode(UiLevel.ADVANCED)
    advanced = not_hidden(window)

    assert simple == len(SIMPLE_FIELDS)
    assert advanced == sum(len(p.rows()) for p in window._panels.values())
    assert simple < advanced


def test_sections_with_nothing_simple_disappear(window):
    """An empty section header is worse than no header.

    Asserted on isHidden(), not isVisible(): the window is never shown in a
    headless test, so isVisible() is false for everything regardless of what
    the mode did.
    """
    window._set_mode(UiLevel.SIMPLE)
    for key, section in window._accordion.sections().items():
        has_simple = window._panels[key].simple_row_count() > 0
        assert section.isHidden() != has_simple, key

    window._set_mode(UiLevel.ADVANCED)
    assert not any(s.isHidden() for s in window._accordion.sections().values())


def test_every_simple_field_actually_exists_as_a_row(window):
    """A typo in SIMPLE_FIELDS would silently shrink Simple mode."""
    every = {p for panel in window._panels.values() for p in panel.rows()}
    assert every >= SIMPLE_FIELDS, SIMPLE_FIELDS - every


def test_the_mode_survives_a_round_trip_through_settings(window):
    window._settings.set_ui_mode(UiLevel.SIMPLE.name)
    window._restore_mode()
    assert window._mode is UiLevel.SIMPLE


def test_toggling_alternates(window):
    window._set_mode(UiLevel.SIMPLE)
    window._toggle_mode()
    assert window._mode is UiLevel.ADVANCED
    window._toggle_mode()
    assert window._mode is UiLevel.SIMPLE


# -- mode and filter compose -----------------------------------------------


def test_filtering_in_simple_searches_only_what_simple_shows(window):
    """A filter hit inside Simple mode must still be a Simple field.

    Note "splice" legitimately matches output.continuous, whose explanation
    mentions that roll media removes splices - so the assertion is on which
    rows survive, not on there being none.
    """
    window._set_mode(UiLevel.SIMPLE)
    window._accordion.filter_edit.setText("splice")
    survivors = {
        path
        for panel in window._panels.values()
        for path, row in panel.rows().items()
        if not row.isHidden()
    }
    assert survivors, "expected at least one Simple field to mention splices"
    assert survivors <= SIMPLE_FIELDS
    assert "printing.splice_mode" not in survivors


def test_a_search_matching_only_hidden_fields_says_so(window):
    """Otherwise the setting looks like it was removed from the application."""
    window._set_mode(UiLevel.SIMPLE)
    window._accordion.filter_edit.setText("splice")
    assert "Advanced" in window._accordion.mode_note.text()


def test_clearing_the_filter_restores_the_mode_not_everything(window):
    window._set_mode(UiLevel.SIMPLE)
    window._accordion.filter_edit.setText("splice")
    window._accordion.filter_edit.setText("")
    assert not_hidden(window) == len(SIMPLE_FIELDS)


def test_activating_a_hidden_field_switches_to_advanced(window):
    """A blocking finding on an Advanced field must not be a dead end."""
    window._set_mode(UiLevel.SIMPLE)
    assert not visible_at("printing.splice_overlap_mm", UiLevel.SIMPLE)
    window._focus_field("printing.splice_overlap_mm")
    assert window._mode is UiLevel.ADVANCED


def test_focus_expands_the_section_that_owns_the_row(window):
    """Design owns printing.* rows, so the config prefix is the wrong key."""
    window._set_mode(UiLevel.ADVANCED)
    for section in window._accordion.sections().values():
        section.set_expanded(False)
    window._focus_field("printing.cut_marks")
    assert window._accordion.section("design").is_expanded()
    assert not window._accordion.section("printing").is_expanded()


# -- the stale badge -------------------------------------------------------


def test_a_resolved_warning_clears_the_header_colour(window):
    """A header that went amber once stayed amber for the whole session."""
    section = window._accordion.section("dimensions")
    section.set_severity(Severity.ERROR, 2)
    assert section.header.styleSheet()
    section.set_severity(None, 0)
    assert section.header.styleSheet() == ""
    assert "!" not in section.header.text()


# -- section numbering -----------------------------------------------------


def visible_numbers(window) -> list[int]:
    return [
        s.number() for s in window._accordion.sections().values() if not s.isHidden()
    ]


def test_the_numbers_have_no_gaps_in_either_mode(window):
    """'1, 2, 4, 6, 7' sends the user looking for sections that are not missing."""
    for mode in (UiLevel.SIMPLE, UiLevel.ADVANCED):
        window._set_mode(mode)
        numbers = visible_numbers(window)
        assert numbers == list(range(1, len(numbers) + 1)), mode.name


def test_renumbering_keeps_a_badge(window):
    """The header text is rebuilt from the number, so a naive fix would lose it."""
    window._set_mode(UiLevel.ADVANCED)
    section = window._accordion.section("scanner")
    section.set_severity(Severity.ERROR, 3)
    section.set_number(2)
    assert "! 3" in section.header.text()
    assert section.header.text().startswith("2.")


def test_switching_modes_does_not_lose_a_badge(window):
    """Both sections carrying it stay in Simple, so the badge must survive."""
    window._store.update_section(
        "dimensions", pitch_mm=25.0, symbol_size_mm=40.0
    )
    window._controller.recompute()
    window._set_mode(UiLevel.SIMPLE)
    header = window._accordion.section("dimensions").header
    assert "!" in header.text()
    assert header.styleSheet()


# -- inert controls --------------------------------------------------------


def test_qr_parameters_are_dead_under_data_matrix(window):
    """Live, they invite the user to set a level and watch nothing change."""
    from aops.core.enums import Symbology

    rows = window._panels["symbol"].rows()
    assert window._store.config.symbol.symbology is Symbology.DATA_MATRIX
    assert not rows["symbol.qr_ecc"].isEnabled()
    assert not rows["symbol.qr_version"].isEnabled()

    window._store.update_section("symbol", symbology=Symbology.QR)
    window._controller.recompute()
    assert rows["symbol.qr_ecc"].isEnabled()
    assert rows["symbol.qr_version"].isEnabled()


# -- the job bar -----------------------------------------------------------


def test_the_job_bar_is_on_screen_in_both_modes(window):
    """It describes the strip, not a setting group, so no mode hides it."""
    for mode in (UiLevel.SIMPLE, UiLevel.ADVANCED):
        window._set_mode(mode)
        assert not window._job_bar.isHidden()


def test_the_job_bar_fields_left_the_accordion_simple_set(window):
    """Otherwise Simple mode's section 10 duplicates the top of the window."""
    assert JOB_BAR_FIELDS
    assert not (JOB_BAR_FIELDS & SIMPLE_FIELDS)
    window._set_mode(UiLevel.SIMPLE)
    assert window._accordion.section("project").isHidden()


def test_a_finding_on_a_job_bar_field_does_not_switch_modes(window):
    """Switching to Advanced to reach a box already on screen would be a lie.

    Asserted on focusWidget() rather than hasFocus(): the window is never shown
    in a headless test, so no widget in it holds real keyboard focus - but Qt
    still records which one would.
    """
    window._set_mode(UiLevel.SIMPLE)
    window._focus_field("project.strip_id")
    assert window._mode is UiLevel.SIMPLE
    assert window.focusWidget() is window._job_bar.strip_edit


def ask_for_travel(window, millimetres: float) -> None:
    """Drive the spin box the way a user would, then settle the pipeline.

    Goes through the widget rather than calling the window's slot directly: the
    rounding note is recorded on the way in, so a test that skipped the box
    would not be exercising the path that produces it.
    """
    window._job_bar.travel_spin.setValue(millimetres)
    window._controller.recompute()


def test_asking_for_an_axis_travel_sets_the_index_range(window):
    from aops.core.positions import travel_mm

    window._store.update_section("dimensions", pitch_mm=25.0)
    window._controller.recompute()
    ask_for_travel(window, 2000.0)

    cfg = window._store.config
    # 80, not 81: the first code sits at zero, so 2000 mm is 80 pitches away.
    assert cfg.position.end_index == 80
    assert travel_mm(cfg.position, window._controller.derived.cell) == pytest.approx(2000.0)


def test_a_travel_that_is_not_a_whole_number_of_codes_rounds_up_and_says_so(window):
    window._store.update_section("dimensions", pitch_mm=25.0)
    window._controller.recompute()
    ask_for_travel(window, 2010.0)

    assert window._store.config.position.end_index == 81  # 2025 mm, not 2000
    assert "2025.0" in window._job_bar.note.text()


def test_the_rounding_note_does_not_outlive_the_request(window):
    """Held on to, it would blame a later pitch change on the rounding."""
    window._store.update_section("dimensions", pitch_mm=25.0)
    window._controller.recompute()
    ask_for_travel(window, 2010.0)
    assert window._job_bar.note.text()

    window._store.update_section("dimensions", pitch_mm=30.0)
    window._controller.recompute()
    assert window._job_bar.note.text() == ""


def test_the_travel_box_does_not_grow_the_strip_on_every_refresh(window):
    """The write-back is guarded; without it, rounding up would compound."""
    window._store.update_section("dimensions", pitch_mm=25.0)
    window._controller.recompute()
    ask_for_travel(window, 2010.0)
    settled = window._store.config.position.end_index

    for _ in range(3):
        window._job_bar.update_from(window._store.config, window._controller.derived)
        window._controller.recompute()
    assert window._store.config.position.end_index == settled


def test_an_unresolved_geometry_does_not_guess_an_index_range(window):
    """The pitch itself may be what is wrong, so there is nothing to convert."""
    window._store.update_section("dimensions", pitch_mm=0.0)
    window._controller.recompute()
    assert window._controller.derived is None

    before = window._store.config.position.end_index
    window._on_travel_requested(5000.0)
    assert window._store.config.position.end_index == before


def test_the_job_bar_reports_what_the_settings_produce(window):
    window._controller.recompute()
    text = window._job_bar.readout.text()
    assert "421 codes" in text
    assert "25.000 mm apart" in text


# -- designing from the job ------------------------------------------------


def test_design_derives_the_geometry_and_is_one_undo_step(window):
    """The job inputs are the truth; a hand-tweak is overwritten but Ctrl+Z
    restores it. That was the chosen contract - recompute everything."""
    window._store.update_section(
        "scanner", mount_distance_mm=150.0, axis_speed_mm_per_s=1000.0
    )
    window._store.update_section("dimensions", symbol_size_mm=33.0)  # the tweak
    window._controller.recompute()

    solution = window.design_for_job(2000.0)
    assert solution is not None and solution.feasible
    assert window._store.config.dimensions.symbol_size_mm != 33.0
    assert window._store.config.scanner.exposure_us <= 1000

    window._store.undo()
    assert window._store.config.dimensions.symbol_size_mm == 33.0


def test_design_needs_a_travel(window):
    assert window.design_for_job(0.0) is None


def test_a_designed_strip_is_exportable(window):
    """The solver's whole promise, exercised through the window's own path."""
    window._store.update_section("scanner", mount_distance_mm=150.0)
    window._controller.recompute()
    window.design_for_job(2000.0)
    window._controller.recompute()
    assert not window._controller.report.blocks_export
    assert window._act_export.isEnabled()


def test_design_leaves_the_job_identity_alone(window):
    window._store.update_section("project", machine="LATHE-04", strip_id="X-AXIS")
    window.design_for_job(2000.0)
    assert window._store.config.project.machine == "LATHE-04"
    assert window._store.config.project.strip_id == "X-AXIS"


# -- fix everything --------------------------------------------------------


def test_fix_everything_is_one_undo_step(window):
    """Eight corrections, one Ctrl+Z. An undo stack fifteen deep is
    archaeology, not undo."""
    window._store.update_section("dimensions", pitch_mm=25.0, symbol_size_mm=40.0)
    window._store.update_section("payload", digits=2)
    before = window._store.config
    window._controller.recompute()

    result = window.fix_everything()
    assert len(result.steps) >= 2
    window._controller.recompute()
    assert not window._controller.report.blocks_export

    window._store.undo()
    assert window._store.config == before


def test_fix_everything_on_a_clean_config_changes_nothing(window):
    window._store.update_section("project", strip_id="X-AXIS")
    before = window._store.config
    assert not window.fix_everything().changed
    assert window._store.config == before


def test_the_fix_all_button_tracks_whether_there_is_anything_to_fix(window):
    window._store.update_section("project", strip_id="X-AXIS", revision="A")
    window._controller.recompute()
    assert not window._issues.fix_all_button.isEnabled()

    window._store.update_section("payload", digits=2)
    window._controller.recompute()
    assert window._issues.fix_all_button.isEnabled()


# -- the Simple-mode length row --------------------------------------------


def test_the_length_row_is_a_simple_field_inside_the_position_section(window):
    """The length editor lives in the panel too, not only on the job bar."""
    window._set_mode(UiLevel.SIMPLE)
    rows = window._panels["position"].rows()
    assert "position.travel_mm" in rows
    assert not rows["position.travel_mm"].isHidden()
    assert not window._accordion.section("position").isHidden()


def test_typing_a_length_adjusts_the_number_of_codes(window):
    window._store.update_section("dimensions", pitch_mm=10.0)
    window._controller.recompute()

    panel = window._panels["position"]
    panel.travel.setValue(2000.0)
    window._controller.recompute()

    cfg = window._store.config
    assert cfg.position.end_index == 200  # 201 codes cover 2000 mm at 10 mm
    assert panel.codes.text() == "201"


def test_the_panel_length_and_the_job_bar_mirror_each_other(window):
    window._store.update_section("dimensions", pitch_mm=10.0)
    window._controller.recompute()

    window._panels["position"].travel.setValue(1500.0)
    window._controller.recompute()
    assert window._job_bar.travel_spin.value() == pytest.approx(1500.0)

    window._job_bar.travel_spin.setValue(500.0)
    window._controller.recompute()
    assert window._panels["position"].travel.value() == pytest.approx(500.0)


def test_a_length_that_is_not_whole_codes_rounds_up(window):
    """Stopping short leaves the axis end uncoded, so the range always covers."""
    window._store.update_section("dimensions", pitch_mm=10.0)
    window._controller.recompute()
    window._panels["position"].travel.setValue(1995.0)
    window._controller.recompute()
    assert window._store.config.position.end_index == 200  # 2000 mm, not 1990


# -- the Simple-mode style picker ------------------------------------------


def test_the_style_picker_is_a_simple_field_in_the_design_section(window):
    window._set_mode(UiLevel.SIMPLE)
    rows = window._panels["design"].rows()
    assert "design.style" in rows
    assert not rows["design.style"].isHidden()
    assert not window._accordion.section("design").isHidden()


def test_picking_plain_strips_the_furniture_in_one_undo_step(window):
    from aops.core.design import detect_style
    from aops.core.enums import PrintStyle
    from aops.ui.widgets.field_row import COMBO_VALUES

    window._set_mode(UiLevel.SIMPLE)
    combo = window._panels["design"].style_combo
    before = window._store.config

    values = getattr(combo, COMBO_VALUES)
    combo.setCurrentIndex(values.index(PrintStyle.PLAIN))

    cfg = window._store.config
    assert detect_style(cfg) is PrintStyle.PLAIN
    assert not cfg.output.human_readable
    assert not cfg.output.engineering_ruler

    window._store.undo()
    assert window._store.config == before


# -- the Simple-mode climate picker ----------------------------------------


def test_the_climate_picker_is_a_simple_field(window):
    window._set_mode(UiLevel.SIMPLE)
    rows = window._panels["media"].rows()
    assert "media.climate" in rows
    assert not rows["media.climate"].isHidden()
    # The raw swing numbers it stands for stay Advanced.
    assert rows["media.rh_swing_percent"].isHidden()
    assert rows["media.temp_swing_deg_c"].isHidden()


def test_a_fresh_configuration_reads_as_a_named_climate_not_custom(window):
    """Defaults matching FACTORY is deliberate - Custom on first launch would
    say the tool does not understand its own defaults."""
    from aops.core.enums import Climate
    from aops.core.media import detect_climate

    assert detect_climate(window._store.config.media) is Climate.FACTORY


def test_picking_a_climate_writes_both_swings_in_one_undo_step(window):
    from aops.core.enums import Climate
    from aops.ui.widgets.field_row import COMBO_VALUES

    combo = window._panels["media"].climate_combo
    before = window._store.config

    values = getattr(combo, COMBO_VALUES)
    combo.setCurrentIndex(values.index(Climate.HARSH))

    cfg = window._store.config
    assert cfg.media.temp_swing_deg_c == 50.0
    assert cfg.media.rh_swing_percent == 70.0

    window._store.undo()
    assert window._store.config == before


def test_hand_tuned_swings_read_back_as_custom(window):
    from aops.core.enums import Climate
    from aops.core.media import detect_climate

    window._store.update_section("media", temp_swing_deg_c=17.0)
    window._controller.recompute()
    assert detect_climate(window._store.config.media) is Climate.CUSTOM
    assert "Custom" in window._panels["media"].climate_note.text() or (
        "hand" in window._panels["media"].climate_note.text()
    )


def test_a_harsher_climate_predicts_more_drift(window):
    """The picker must actually reach the accuracy model, or it is decoration."""
    from aops.core.enums import Climate
    from aops.core.media import CLIMATE_SWINGS
    from aops.core.stats import derive

    def drift(climate):
        window._panels["media"]._apply_climate_choice(climate)
        return derive(window._store.config).accuracy.environmental_drift_mm

    assert drift(Climate.HARSH) > drift(Climate.CONDITIONED)
    assert set(CLIMATE_SWINGS[Climate.HARSH]) == {"temp_swing_deg_c", "rh_swing_percent"}


# -- the test-page coupon ---------------------------------------------------


def test_the_coupon_is_one_sheet_of_the_real_strip(window):
    from aops.core.stats import derive

    window._store.update_section("dimensions", pitch_mm=10.0)
    window._controller.recompute()
    window._panels["position"].travel.setValue(2000.0)
    window._controller.recompute()

    coupon = window.coupon_config()
    assert coupon is not None
    d = derive(coupon)
    assert len(d.pages) == 1
    assert not coupon.output.continuous
    assert not coupon.output.instruction_page
    assert coupon.output.calibration_bar  # the point of the bench sheet

    # Same strip, same payloads: the coupon's codes are the strip's first codes.
    full = window._controller.derived
    assert d.payloads == full.payloads[: len(d.payloads)]
    assert len(d.payloads) >= 2


def test_the_coupon_does_not_touch_the_live_configuration(window):
    before = window._store.config
    window.coupon_config()
    assert window._store.config == before


def test_a_job_shorter_than_one_page_is_not_padded(window):
    from aops.core.stats import derive

    window._store.update_section("position", end_index=3)
    window._controller.recompute()
    coupon = window.coupon_config()
    assert coupon.position.end_index == 3
    assert derive(coupon).code_count == 4


def test_the_test_page_action_gates_with_the_other_exports(window):
    window._store.update_section("payload", digits=2)  # blocking
    window._controller.recompute()
    assert not window._act_test_page.isEnabled()

    window._store.update_section("payload", digits=6)
    window._controller.recompute()
    assert window._act_test_page.isEnabled()


# -- conflicts are put to the user -----------------------------------------


def conflicted_config():
    """The pitch fight: reader window vs cutting tolerance (see core tests)."""
    from aops.core.config import DimensionConfig
    from aops.core.presets import BUILT_IN_PRESETS
    from aops.core.presets import apply as apply_preset

    cfg = apply_preset(
        next(p for p in BUILT_IN_PRESETS if "NVF230" in p.name), AopsConfig()
    )
    return dc.replace(
        cfg,
        scanner=dc.replace(cfg.scanner, mount_distance_mm=62.0, min_codes_in_view=3),
        dimensions=DimensionConfig(
            pitch_mm=15.0, symbol_size_mm=12.0, quiet_zone_mm=0.5, strip_height_mm=40.0
        ),
    )


def test_ruling_for_the_challenger_applies_its_value(window):
    window._store.set_config(conflicted_config())
    result = window.fix_everything()
    assert result.conflicts
    fight = result.conflicts[0]

    window.resolve_conflict(fight, "challenger")
    assert window._store.config.dimensions.pitch_mm == fight.challenger_value

    window._store.undo()
    assert window._store.config.dimensions.pitch_mm == fight.incumbent_value


def test_ruling_for_the_incumbent_keeps_its_value(window):
    window._store.set_config(conflicted_config())
    result = window.fix_everything()
    fight = result.conflicts[0]

    window.resolve_conflict(fight, "incumbent")
    assert window._store.config.dimensions.pitch_mm == fight.incumbent_value


def test_the_dialog_names_both_rules_and_never_picks_for_you(window):
    from aops.ui.dialogs.conflict_dialog import ConflictDialog

    window._store.set_config(conflicted_config())
    fight = window.fix_everything().conflicts[0]

    dialog = ConflictDialog(fight, window)
    assert dialog.choice is None
    text = (
        dialog.challenger_button.text()
        + dialog.incumbent_button.text()
        + dialog.job_button.text()
    )
    assert fight.challenger_rule in text
    assert fight.incumbent_rule in text
    assert "Design strip" in text

    dialog.challenger_button.click()
    assert dialog.choice == "challenger"


# -- the issues list -------------------------------------------------------


def test_issues_are_never_behind_a_tab(window):
    """The reason the export button is greyed out must not need a click to see."""
    titles = {window._tabs.tabText(i) for i in range(window._tabs.count())}
    assert "Issues" not in titles
    assert not window._issues.isHidden()


def test_the_issues_heading_carries_the_count_even_when_collapsed(window):
    """Shrunk to nothing in the splitter, the heading is all that is left."""
    window._store.update_section("payload", digits=2)
    window._controller.recompute()
    assert "blocking" in window._issues.heading.text()
    assert window._issues.heading.styleSheet()

    window._store.update_section("payload", digits=6)
    window._controller.recompute()
    assert "blocking" not in window._issues.heading.text()


def test_the_issues_heading_does_not_claim_none_while_listing_notes(window):
    """A green 'none' directly above two visible lines reads as a bug."""
    # A default project has no strip ID, which is a warning in its own right.
    window._store.update_section("project", strip_id="X-AXIS")
    window._controller.recompute()

    report = window._controller.report
    assert [f for f in report.findings if f.severity is Severity.INFO]
    assert not [f for f in report.findings if f.severity >= Severity.WARNING]

    heading = window._issues.heading.text()
    assert "none blocking" in heading
    assert "note" in heading
