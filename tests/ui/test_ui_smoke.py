"""Headless GUI smoke tests.

Run with ``QT_QPA_PLATFORM=offscreen``. These assert the behaviours that make
the interface trustworthy rather than merely present: that live validation
actually blocks export, that the preview updates without a Generate button, and
that a project round-trips through the UI unchanged.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from aops.core.config import AopsConfig  # noqa: E402
from aops.core.enums import Media, Symbology  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from aops.app import create_app

    existing = QApplication.instance()
    yield existing or create_app([])


@pytest.fixture
def window(app):
    from aops.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    app.processEvents()
    win._controller.recompute()
    app.processEvents()
    yield win
    # Mark clean before closing: closeEvent otherwise raises the unsaved-changes
    # QMessageBox, which blocks forever when there is no user to answer it.
    win._store.mark_saved()
    win.close()
    app.processEvents()


def pump(app, window) -> None:
    """Force the debounced pipeline to run and the views to update."""
    window._controller.recompute()
    for _ in range(3):
        app.processEvents()


def test_window_constructs_with_all_sections(window):
    from aops.ui.panels.sections import PANEL_SPECS

    assert window._accordion.sections()
    # Tied to the registry rather than a literal, so adding a section does not
    # need this number edited to stay honest.
    assert len(window._panels) == len(PANEL_SPECS)
    assert set(window._panels) == {key for key, _title, _cls in PANEL_SPECS}
    assert window._pill.text()


def test_preview_updates_without_a_generate_button(app, window):
    before = window._preview._item.boundingRect().width()
    window._store.update_section("dimensions", pitch_mm=40.0)
    pump(app, window)
    after = window._preview._item.boundingRect().width()
    assert after != before, "changing the pitch must update the preview immediately"


def test_invalid_geometry_blocks_export_and_names_the_rule(app, window):
    window._store.update_section("dimensions", symbol_size_mm=30.0)
    pump(app, window)
    assert not window._act_export.isEnabled()
    assert "GEO-003" in window._act_export.toolTip()
    assert "BLOCKED" in window._pill.text()

    window._store.update_section("dimensions", symbol_size_mm=10.0)
    pump(app, window)
    assert window._act_export.isEnabled()


def test_unimplemented_symbology_is_fatal_and_never_substituted(app, window):
    window._store.update_section("symbol", symbology=Symbology.CODE128)
    pump(app, window)
    assert not window._act_export.isEnabled()
    assert "SYM-001" in window._act_export.toolTip()
    # The configuration keeps the real enum; Qt must not downgrade it to a str.
    assert isinstance(window._store.config.symbol.symbology, Symbology)


def test_paper_media_is_rejected_for_a_long_strip(app, window):
    window._store.update_section("media", media=Media.PAPER)
    pump(app, window)
    ids = {f.rule_id for f in window._controller.report.findings}
    assert "MED-001" in ids
    assert not window._act_export.isEnabled()


def test_combo_values_survive_qt_round_trip(app, window):
    """StrEnum members must not be flattened into bare strings."""
    panel = window._panels["media"]
    row = panel.rows()["media.media"]
    row.editor.setCurrentIndex(0)
    pump(app, window)
    assert isinstance(window._store.config.media.media, Media)


def test_undo_redo_restores_configuration(app, window):
    original = window._store.config.dimensions.pitch_mm
    window._store.update_section("dimensions", pitch_mm=33.0)
    pump(app, window)
    assert window._store.config.dimensions.pitch_mm == 33.0

    window._store.undo()
    pump(app, window)
    assert window._store.config.dimensions.pitch_mm == original


def test_project_round_trips_through_the_ui(app, window, tmp_path):
    from aops import __version__
    from aops.core.project_io import dump_project, load_project

    window._store.update_section("project", machine="GANTRY-01", strip_id="AX1")
    window._store.update_section("dimensions", pitch_mm=30.0)
    pump(app, window)

    path = tmp_path / "roundtrip.aops"
    path.write_text(dump_project(window._store.config, app_version=__version__))
    reloaded = load_project(path.read_text()).config

    assert reloaded == window._store.config


def test_derived_readouts_populate(app, window):
    window._store.set_config(AopsConfig())
    pump(app, window)
    assert window._panels["position"].formula.text().startswith("P [mm]")
    assert window._panels["scanner"].fov.text() == "35.0"
    assert "421" in window._status_pages.text()


def test_issue_activation_focuses_the_offending_field(app, window):
    window._store.update_section("dimensions", symbol_size_mm=30.0)
    pump(app, window)
    window._focus_field("dimensions.symbol_size_mm")
    app.processEvents()
    section = window._accordion.section("dimensions")
    assert section is not None
    assert section.body.isVisible()
