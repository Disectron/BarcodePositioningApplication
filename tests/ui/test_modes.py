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
    from aops.ui.main_window import MainWindow
    from aops.ui.settings_store import SettingsStore

    monkeypatch.setattr(SettingsStore, "presets_dir", lambda self: tmp_path)
    monkeypatch.setattr(SettingsStore, "set_ui_mode", lambda self, name: None)
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

    An error is clearable if the control it points at is in the Simple set, or
    if it carries a one-click Fix - the Issues list is visible in both modes,
    and activating a finding switches to Advanced on the user's behalf.
    """
    unreachable = []
    for finding in errors_for(SIMPLE_MISTAKES[label]):
        reachable = (
            finding.field in SIMPLE_FIELDS
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
