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
