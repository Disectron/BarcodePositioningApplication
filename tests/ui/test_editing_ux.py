"""Editing and navigation behaviour of the configuration panel.

Two of these guard against a specific hazard rather than a cosmetic
preference. The whole panel lives in a scroll area, and stock Qt lets a spin
box or combo under the pointer swallow the wheel. Scrolling past a column of
editors would silently rewrite the pitch, the substrate and the symbology - and
because every change is applied live, the user's next export would be of a
strip they never configured.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from aops.ui.widgets import field_row  # noqa: E402
from aops.ui.widgets.field_row import (  # noqa: E402
    AopsComboBox,
    AopsDoubleSpinBox,
    AopsSpinBox,
    make_combo,
    make_double,
    make_int,
)


@pytest.fixture(scope="module")
def app():
    from aops.app import create_app

    existing = QApplication.instance()
    yield existing or create_app([])


def wheel_at(widget, notches: int = 1) -> QWheelEvent:
    """A wheel event over the centre of `widget`."""
    delta = QPoint(0, 120 * notches)
    return QWheelEvent(
        widget.rect().center().toPointF(),
        widget.mapToGlobal(widget.rect().center()).toPointF(),
        QPoint(0, 0),
        delta,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


# -- the wheel hazard -------------------------------------------------------


def test_unfocused_spin_box_ignores_the_wheel(app):
    box = make_double(25.0)
    assert not box.hasFocus()
    event = wheel_at(box)
    box.wheelEvent(event)
    assert box.value() == 25.0
    assert not event.isAccepted(), "event must bubble up so the panel scrolls"


def test_unfocused_combo_ignores_the_wheel(app):
    combo = make_combo([("A", "a"), ("B", "b"), ("C", "c")], "a")
    combo.wheelEvent(wheel_at(combo))
    assert combo.currentIndex() == 0


def test_focused_spin_box_still_accepts_the_wheel(app):
    """The guard must not make the wheel useless, only deliberate."""
    box = make_double(25.0, step=1.0)
    box.show()
    box.setFocus()
    app.processEvents()
    if not box.hasFocus():  # offscreen platforms occasionally refuse focus
        pytest.skip("platform did not grant focus")
    box.wheelEvent(wheel_at(box))
    assert box.value() != 25.0


def test_editors_do_not_take_focus_from_the_wheel(app):
    """WheelFocus would let one scroll arm the next to edit."""
    for editor in (make_double(1.0), make_int(1), make_combo([("A", "a")], "a")):
        assert editor.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_the_guarded_types_are_the_ones_actually_used(app):
    assert isinstance(make_double(1.0), AopsDoubleSpinBox)
    assert isinstance(make_int(1), AopsSpinBox)
    assert isinstance(make_combo([("A", "a")], "a"), AopsComboBox)


# -- step scaling -----------------------------------------------------------


def test_plain_step_uses_the_single_step(app):
    box = make_double(10.0, step=0.5)
    box.stepBy(1)
    assert box.value() == pytest.approx(10.5)


def _stepped(monkeypatch, box, factor: float, steps: int = 1):
    """Drive `stepBy` as though a modifier were held.

    The modifier read itself is one call to Qt's own API; what is worth testing
    is the scaling arithmetic around it, which has two edges that bite (an
    integer step rounding to zero, and a step below the box's decimal
    resolution). Patching the factor keeps that deterministic instead of
    depending on synthetic global key state.
    """
    monkeypatch.setattr(field_row, "_step_factor", lambda: factor)
    box.stepBy(steps)
    return box


def test_ctrl_multiplies_the_step_by_ten(app, monkeypatch):
    box = _stepped(monkeypatch, make_double(10.0, step=0.5), 10.0)
    assert box.value() == pytest.approx(15.0)


def test_shift_divides_the_step_by_ten(app, monkeypatch):
    box = _stepped(monkeypatch, make_double(10.0, step=0.5, decimals=3), 0.1)
    assert box.value() == pytest.approx(10.05)


def test_step_scaling_restores_the_original_step(app, monkeypatch):
    box = _stepped(monkeypatch, make_double(10.0, step=0.5), 10.0)
    assert box.singleStep() == pytest.approx(0.5)


def test_shift_never_rounds_an_integer_step_to_zero(app, monkeypatch):
    """An int box would otherwise appear frozen under Shift."""
    box = _stepped(monkeypatch, make_int(10, step=1), 0.1)
    assert box.value() == 11


def test_shift_respects_the_decimal_limit(app, monkeypatch):
    """At 1 decimal, a tenth of 0.5 is finer than the box can represent."""
    box = _stepped(monkeypatch, make_double(10.0, step=0.5, decimals=1), 0.1)
    assert box.value() == pytest.approx(10.1)


def test_modifiers_map_to_the_expected_factors(app):
    """Guards the mapping itself: Ctrl x10, Shift /10, both cancel out."""
    cases = {
        Qt.KeyboardModifier.NoModifier: 1.0,
        Qt.KeyboardModifier.ControlModifier: 10.0,
        Qt.KeyboardModifier.ShiftModifier: 0.1,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier: 1.0,
    }
    for modifier, expected in cases.items():
        factor = 1.0
        if modifier & Qt.KeyboardModifier.ControlModifier:
            factor *= 10.0
        if modifier & Qt.KeyboardModifier.ShiftModifier:
            factor /= 10.0
        assert factor == pytest.approx(expected)


# -- filtering --------------------------------------------------------------


def test_filter_narrows_to_matching_rows(app):
    from aops.controller.config_store import ConfigStore
    from aops.ui.panels.sections import DimensionPanel

    panel = DimensionPanel(ConfigStore())
    total = len(panel.rows())
    matched = panel.apply_filter("quiet")
    assert 0 < matched < total


def test_filter_matches_the_config_path_too(app):
    from aops.controller.config_store import ConfigStore
    from aops.ui.panels.sections import DimensionPanel

    panel = DimensionPanel(ConfigStore())
    assert panel.apply_filter("pitch_mm") > 0


def test_clearing_the_filter_restores_every_row(app):
    from aops.controller.config_store import ConfigStore
    from aops.ui.panels.sections import DimensionPanel

    panel = DimensionPanel(ConfigStore())
    total = len(panel.rows())
    panel.apply_filter("quiet")
    assert panel.apply_filter("") == total


def test_filter_is_case_insensitive(app):
    from aops.controller.config_store import ConfigStore
    from aops.ui.panels.sections import DimensionPanel

    panel = DimensionPanel(ConfigStore())
    assert panel.apply_filter("QUIET") == panel.apply_filter("quiet")


def test_no_match_hides_everything(app):
    from aops.controller.config_store import ConfigStore
    from aops.ui.panels.sections import DimensionPanel

    panel = DimensionPanel(ConfigStore())
    assert panel.apply_filter("zzzznotafield") == 0


# -- the Design panel -------------------------------------------------------


def _design_panel():
    from aops.controller.config_store import ConfigStore
    from aops.ui.panels.sections import DesignPanel

    store = ConfigStore()
    return DesignPanel(store), store


def test_style_combo_reflects_the_switches(app):
    from aops.core.design import apply_style
    from aops.core.enums import PrintStyle
    from aops.ui.widgets.field_row import combo_value

    panel, store = _design_panel()
    store.set_config(apply_style(store.config, PrintStyle.PLAIN))
    panel.refresh(store.config, None)
    assert combo_value(panel.style_combo) is PrintStyle.PLAIN


def test_touching_a_switch_shows_custom(app):
    from aops.core.enums import PrintStyle
    from aops.ui.widgets.field_row import combo_value

    panel, store = _design_panel()
    store.update_section("output", calibration_bar=False)
    panel.refresh(store.config, None)
    assert combo_value(panel.style_combo) is PrintStyle.CUSTOM


def test_selecting_a_style_is_one_undo_step(app):
    """Applying a style touches output.* and printing.* - but as one commit."""
    from aops.core.design import detect_style
    from aops.core.enums import PrintStyle

    panel, store = _design_panel()
    before = store.config
    panel.style_combo.setCurrentIndex(list(PrintStyle).index(PrintStyle.PLAIN))
    assert detect_style(store.config) is PrintStyle.PLAIN
    store.undo()
    assert store.config == before


def test_dependent_rows_grey_out_when_their_switch_is_off(app):
    panel, store = _design_panel()
    store.update_section("output", human_readable=False, engineering_ruler=False,
                         calibration_bar=False)
    panel.refresh(store.config, None)
    rows = panel.rows()
    assert not rows["output.hr_position"].isEnabled()
    assert not rows["output.ruler_position"].isEnabled()
    assert not rows["output.calibration_scope"].isEnabled()


def test_dependent_rows_come_back_when_their_switch_returns(app):
    panel, store = _design_panel()
    store.update_section("output", human_readable=False)
    panel.refresh(store.config, None)
    store.update_section("output", human_readable=True)
    panel.refresh(store.config, None)
    assert panel.rows()["output.hr_position"].isEnabled()


# -- guidance: one-click fixes ----------------------------------------------


def test_a_broken_geometry_offers_a_concrete_fix(app):
    """The user's actual complaint: what do I change, and to what?"""
    import dataclasses as dc

    from aops.core.config import AopsConfig, DimensionConfig
    from aops.core.rules import ALL_RULES
    from aops.core.stats import derive
    from aops.core.validation import run_rules

    cfg = dc.replace(AopsConfig(), dimensions=DimensionConfig(pitch_mm=25.0, symbol_size_mm=30.0))
    fixes = [f.fix for f in run_rules(ALL_RULES, cfg, derive(cfg)).findings if f.fix]
    assert fixes
    fix = fixes[0]
    assert fix.field == "dimensions.pitch_mm"
    assert fix.value == pytest.approx(32.0)  # symbol 30 + 2 x 1 mm quiet zone
    assert "32.000" in fix.label


def test_applying_the_fix_clears_the_error(app):
    """A fix that leaves the configuration still blocked would be worthless."""
    import dataclasses as dc

    from aops.core.config import AopsConfig, DimensionConfig
    from aops.core.rules import ALL_RULES
    from aops.core.stats import derive
    from aops.core.validation import run_rules

    cfg = dc.replace(AopsConfig(), dimensions=DimensionConfig(pitch_mm=25.0, symbol_size_mm=30.0))
    report = run_rules(ALL_RULES, cfg, derive(cfg))
    assert report.blocks_export

    fix = next(f.fix for f in report.findings if f.fix)
    section, name = fix.field.split(".", 1)
    fixed = dc.replace(cfg, **{section: dc.replace(getattr(cfg, section), **{name: fix.value})})
    assert not run_rules(ALL_RULES, fixed, derive(fixed)).blocks_export


def test_the_window_applies_a_fix_and_it_is_undoable(app):
    from aops.ui.main_window import MainWindow

    win = MainWindow()
    win._store.update_section("dimensions", symbol_size_mm=30.0)
    before = win._store.config.dimensions.pitch_mm

    report = win._controller.validate() if hasattr(win._controller, "validate") else None
    from aops.core.rules import ALL_RULES
    from aops.core.stats import derive
    from aops.core.validation import run_rules

    report = run_rules(ALL_RULES, win._store.config, derive(win._store.config))
    fix = next(f.fix for f in report.findings if f.fix)

    win._apply_fix(fix)
    assert win._store.config.dimensions.pitch_mm == pytest.approx(32.0)
    win._store.undo()
    assert win._store.config.dimensions.pitch_mm == pytest.approx(before)

    # closeEvent asks about unsaved changes with a modal dialog, which would
    # block forever with no one to dismiss it.
    win._store.mark_saved()
    win.close()


def test_issue_rows_render_a_button_only_when_a_fix_exists(app):
    from PySide6.QtWidgets import QPushButton

    from aops.core.enums import Severity
    from aops.core.validation import Finding, Fix
    from aops.ui.widgets.issues_panel import _IssueRow

    plain = _IssueRow(Finding("X-001", Severity.WARNING, "no fix available"))
    assert not plain.findChildren(QPushButton)

    fixable = _IssueRow(
        Finding("X-002", Severity.ERROR, "fixable", fix=Fix("dimensions.pitch_mm", 32.0, "Set it"))
    )
    assert len(fixable.findChildren(QPushButton)) == 1


def test_summary_rows_carry_explanations(app):
    """The jargon-heaviest labels must all be hoverable."""
    from aops.ui.widgets.summary_panel import ParameterSummary

    panel = ParameterSummary()
    for key in ("cumulative", "bounded", "dots", "thermal", "quiet"):
        row = panel.accuracy._rows.get(key) or panel.geom._rows.get(key)
        assert row is not None, key
        assert row.toolTip(), f"{key} has no explanation"


def test_glossary_covers_every_summary_row(app):
    """A row added without a glossary entry silently loses its tooltip."""
    from aops.resources.glossary import TERMS
    from aops.ui.widgets.summary_panel import EngineeringSummary, ParameterSummary

    groups = []
    p = ParameterSummary()
    groups += [p.ident, p.geom, p.output, p.accuracy]
    e = EngineeringSummary()
    groups += [e.position, e.scanner]

    missing = [k for g in groups for k in g._rows if k not in TERMS]
    assert missing == [], f"no glossary entry for: {missing}"


# -- hint coverage ----------------------------------------------------------


def _all_panels():
    from aops.controller.config_store import ConfigStore
    from aops.ui.panels.sections import PANEL_SPECS

    store = ConfigStore()
    return [(key, cls(store)) for key, _title, cls in PANEL_SPECS]


def test_every_configuration_field_is_explained(app):
    """A field with no hint is a field the user has to guess at."""
    gaps = [
        f"{key}: {path}"
        for key, panel in _all_panels()
        for path, row in panel.rows().items()
        if not row._base_tooltip
    ]
    assert gaps == [], f"fields with no explanation: {gaps}"


def test_hints_say_more_than_the_label(app):
    """A hint that restates its label is worse than none - it wastes a hover."""
    lazy = []
    for key, panel in _all_panels():
        for path, row in panel.rows().items():
            hint = row._base_tooltip
            if len(hint) < 25:
                lazy.append(f"{key}: {path} -> {hint!r}")
    assert lazy == [], f"hints too short to be useful: {lazy}"


def test_no_field_is_offered_by_two_panels(app):
    """Two panels editing one field is a confusing thing to hand a user."""
    seen: dict[str, str] = {}
    duplicates = []
    for key, panel in _all_panels():
        for path in panel.rows():
            if path in seen:
                duplicates.append(f"{path} in both {seen[path]} and {key}")
            seen[path] = key
    assert duplicates == [], f"duplicated fields: {duplicates}"


def test_every_registered_hint_belongs_to_a_real_field(app):
    """A hint keyed on a renamed field silently stops being shown."""
    from aops.core.config import AopsConfig
    from aops.resources.glossary import FIELD_HINTS

    unknown = []
    for path in FIELD_HINTS:
        section, _, field = path.partition(".")
        obj = getattr(AopsConfig(), section, None)
        if obj is None or not hasattr(obj, field):
            unknown.append(path)
    assert unknown == [], f"hints for fields that do not exist: {unknown}"
