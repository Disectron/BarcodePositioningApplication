"""The AOPS main window.

Two columns: configuration on the left, preview and summaries on the right, with
a toolbar above and a status bar below.

The window is a view. It owns no derived state - everything it displays comes
from `AppController`, which recomputes it from the configuration. That is what
guarantees the preview, the summaries and the export can never disagree.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from aops import __app_name__, __version__
from aops.controller.app_controller import AppController
from aops.controller.config_store import ConfigStore
from aops.controller.workers import ExportWorker
from aops.core.autofix import AutofixResult, Conflict, autofix
from aops.core.config import AopsConfig
from aops.core.drawlist import DrawList
from aops.core.enums import Severity
from aops.core.errors import AopsError
from aops.core.layout.bands import rows_that_fit, solve_sheet_bands
from aops.core.positions import end_index_for_travel
from aops.core.presets import (
    BUILT_IN_PRESETS,
    Preset,
    dump_preset,
    load_preset,
)
from aops.core.presets import (
    apply as apply_preset,
)
from aops.core.presets import (
    capture as capture_preset,
)
from aops.core.project_io import (
    PROJECT_FILE_SUFFIX,
    dump_project,
    load_project,
)
from aops.core.solve import Solution, solve
from aops.core.stats import DerivedGeometry, derive
from aops.core.validation import ValidationReport
from aops.resources.field_levels import UiLevel, visible_at
from aops.symbols.cache import probe_matrix_cols
from aops.ui.dialogs.about_dialog import AboutDialog, HelpDialog
from aops.ui.dialogs.conflict_dialog import ConflictDialog
from aops.ui.dialogs.export_progress import ExportProgressDialog
from aops.ui.panels.sections import PANEL_SPECS
from aops.ui.settings_store import SettingsStore
from aops.ui.widgets.accordion import AccordionPanel
from aops.ui.widgets.issues_panel import IssuesBox, StatusPill
from aops.ui.widgets.job_bar import JobBar
from aops.ui.widgets.preview_view import OverviewBar, PreviewView
from aops.ui.widgets.summary_panel import EngineeringSummary, ParameterSummary

PROJECT_FILTER = f"AOPS project (*{PROJECT_FILE_SUFFIX});;All files (*)"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(__app_name__)

        self._settings = SettingsStore()
        self._store = ConfigStore()
        self._controller = AppController(self._store)

        self._thread: QThread | None = None
        self._worker: ExportWorker | None = None
        self._progress: ExportProgressDialog | None = None

        self._build_ui()
        self._build_toolbar()
        self._build_status_bar()
        self._connect()
        self._restore_window()
        self._restore_mode()

        self._controller.recompute()

    # -- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter = splitter

        # ---- left: configuration accordion
        self._accordion = AccordionPanel()
        self._panels = {}
        #: Expansion state saved while a filter is active, restored on clear.
        self._expanded_before_filter: dict[str, bool] | None = None
        #: How much of the configuration is on show. Restored from settings
        #: after the panels exist, since applying it needs them.
        self._mode = UiLevel.ADVANCED
        for key, title, panel_cls in PANEL_SPECS:
            section = self._accordion.add_section(key, title)
            panel = panel_cls(self._store, section)
            self._panels[key] = panel
            section.add_widget(panel)
            # Only the first few sections start open; nine expanded sections is
            # a wall of controls.
            section.set_expanded(key in ("symbol", "position", "dimensions"))
        self._accordion.finish()
        self._accordion.filterChanged.connect(self._on_filter_changed)
        self._accordion.modeChanged.connect(self._set_mode)

        left_scroll = QScrollArea(self)
        left_scroll.setWidget(self._accordion)
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(380)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        splitter.addWidget(left_scroll)

        # ---- right: preview + summaries
        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(6)

        preview_header = QHBoxLayout()
        label = QLabel("STRIP PREVIEW  (first 10 symbols)", right)
        label.setProperty("heading", True)
        preview_header.addWidget(label)
        preview_header.addStretch(1)
        self._zoom_label = QLabel("100 %", right)
        self._zoom_label.setProperty("mono", True)
        preview_header.addWidget(self._zoom_label)
        right_layout.addLayout(preview_header)

        self._preview = PreviewView(right)
        self._preview.setMinimumHeight(200)
        right_layout.addWidget(self._preview, 3)

        overview_label = QLabel("FULL STRIP OVERVIEW  (not to scale)", right)
        overview_label.setProperty("heading", True)
        right_layout.addWidget(overview_label)

        self._overview = OverviewBar(right)
        right_layout.addWidget(self._overview)

        self._tabs = QTabWidget(right)
        self._parameter_summary = ParameterSummary(self._tabs)
        self._engineering_summary = EngineeringSummary(self._tabs)

        for widget, title in (
            (self._parameter_summary, "Parameter summary"),
            (self._engineering_summary, "Engineering summary"),
        ):
            scroll = QScrollArea(self._tabs)
            scroll.setWidget(widget)
            scroll.setWidgetResizable(True)
            self._tabs.addTab(scroll, title)
        self._tabs.setMinimumHeight(160)

        # Summaries are reference material and belong behind tabs. Issues are
        # not: they are the reason the export button is greyed out, so they get
        # permanent screen space. The splitter lets a user who wants a taller
        # preview shrink the list to its heading, which still carries the count.
        self._issues = IssuesBox(right)
        lower = QSplitter(Qt.Orientation.Vertical, right)
        lower.addWidget(self._tabs)
        lower.addWidget(self._issues)
        lower.setStretchFactor(0, 1)
        lower.setStretchFactor(1, 1)
        lower.setSizes([220, 180])
        self._lower_splitter = lower
        right_layout.addWidget(lower, 2)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([400, 1000])

        # The job bar spans both columns: it describes the strip as a whole, so
        # putting it inside either column would imply it belonged to one of them.
        self._job_bar = JobBar(self)
        self._job_bar.fieldEdited.connect(self._on_job_field)
        self._job_bar.travelRequested.connect(self._on_travel_requested)
        self._job_bar.designRequested.connect(self.on_design)

        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._job_bar)
        central_layout.addWidget(splitter, 1)

        self.setCentralWidget(central)

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main", self)
        # saveState() identifies toolbars by object name and warns without one,
        # which meant the toolbar was never actually part of the restored state.
        bar.setObjectName("mainToolBar")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(bar)
        self._toolbar = bar

        def add(text: str, slot, shortcut: str | None = None, tip: str = "") -> QAction:
            action = QAction(text, self)
            action.triggered.connect(slot)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            if tip:
                action.setToolTip(tip)
            bar.addAction(action)
            return action

        self._act_new = add("New", self.on_new, "Ctrl+N")
        self._act_open = add("Open", self.on_open, "Ctrl+O")
        self._act_save = add("Save", self.on_save, "Ctrl+S")
        bar.addSeparator()
        self._act_export = add("Export PDF", self.on_export_tiles, "Ctrl+E",
                               "Export tiled sheets.")
        self._act_export_cont = add("Export Continuous", self.on_export_continuous,
                                    None, "Export the continuous single-page strip.")
        self._act_export_rows = add(
            "Export Multi-Row", self.on_export_multirow, None,
            "Export tiled sheets with several strip rows stacked per sheet - "
            "cut apart and join end-to-end. A 2 m strip lands on 2 sheets "
            "instead of 9. Export PDF keeps the classic one-row layout.")
        self._act_test_page = add("Test Page", self.on_export_test_page, None,
                                  "Export one bench sheet: the calibration bar plus the "
                                  "first page of real codes. Print and verify this before "
                                  "committing a full roll.")
        bar.addSeparator()
        self._act_undo = add("Undo", self._store.undo, "Ctrl+Z")
        self._act_redo = add("Redo", self._store.redo, "Ctrl+Y")
        bar.addSeparator()
        self._presets_button = QToolButton(self)
        self._presets_button.setText("Presets")
        self._presets_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._presets_menu = QMenu(self._presets_button)
        self._presets_menu.setToolTipsVisible(True)
        # Rebuilt on every open, so a preset saved a moment ago is there.
        self._presets_menu.aboutToShow.connect(self._rebuild_presets_menu)
        self._presets_button.setMenu(self._presets_menu)
        self._presets_button.setToolTip(
            "Reusable setups: geometry, media, printer and reader.\n"
            "A preset never carries the machine name, strip ID or index range."
        )
        bar.addWidget(self._presets_button)

        bar.addSeparator()
        add("Simple / Advanced", self._toggle_mode, "Ctrl+Shift+A",
            "Switch between the settings a typical strip needs and every setting.")
        add("Find setting", self._accordion.focus_filter, "Ctrl+F",
            "Jump to the filter box and search every section by name.")
        bar.addSeparator()
        add("Fit width", self._preview.fit_width, "Ctrl+0")
        add("1:1", self._preview.zoom_actual)
        bar.addSeparator()
        add("Help", self.on_help, "F1")
        add("About", self.on_about)

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        self._pill = StatusPill(self)
        self._status_detail = QLabel("", self)
        self._status_pages = QLabel("", self)
        self._status_pages.setProperty("mono", True)

        status.addWidget(self._pill)
        status.addWidget(self._status_detail, 1)
        status.addPermanentWidget(self._status_pages)

    def _connect(self) -> None:
        self._controller.derivedChanged.connect(self._on_derived)
        self._controller.validationChanged.connect(self._on_validation)
        self._controller.previewChanged.connect(self._on_preview)
        self._controller.overviewChanged.connect(self._on_overview)
        self._controller.errorRaised.connect(self._on_error)

        self._store.configChanged.connect(self._on_config_changed)
        self._store.dirtyChanged.connect(self._update_title)
        self._store.pathChanged.connect(lambda _p: self._update_title())

        self._preview.zoomChanged.connect(
            lambda _z: self._zoom_label.setText(f"{self._preview.scale_percent():.0f} %")
        )
        self._issues.findingActivated.connect(self._focus_field)
        self._issues.fixRequested.connect(self._apply_fix)
        self._issues.fixAllRequested.connect(self.on_fix_all)

    # -- job bar ------------------------------------------------------------

    @Slot(str, str)
    def _on_job_field(self, path: str, value: str) -> None:
        """Edit made in the job bar rather than in section 10."""
        section, name = path.split(".", 1)
        self._store.update_section(section, **{name: value})

    def fix_everything(self) -> AutofixResult:
        """Run the auto-fixer and commit its outcome as one undoable step.

        Split from `on_fix_all` so tests can exercise it without a dialog.
        """
        result = autofix(self._store.config)
        if result.changed:
            self._store.set_config(result.config)
        return result

    @Slot()
    def on_fix_all(self) -> None:
        result = self.fix_everything()

        if not result.changed and result.clean and not result.conflicts:
            self._status_detail.setText("Nothing to fix.")
            return

        parts = []
        if result.steps:
            parts.append(
                f"Applied {len(result.steps)} correction(s) - one Ctrl+Z "
                "restores all of them:\n\n"
                + "\n".join(s.sentence for s in result.steps)
            )
        if result.unresolved:
            parts.append(
                "Still needing you:\n\n"
                + "\n\n".join(u.sentence for u in result.unresolved)
            )

        show = QMessageBox.information if result.clean else QMessageBox.warning
        show(self, "Fix everything", "\n\n".join(parts))
        self._status_detail.setText(
            f"Auto-fix: {len(result.steps)} applied, "
            f"{len(result.unresolved)} left for you."
        )

        # Fights are put to the user one at a time, after the summary so the
        # question arrives with its context already read. Answering one can
        # dissolve the next, so each later dialog would be built from a stale
        # fight - hence re-running the fixer instead of iterating the list.
        if result.conflicts:
            self._ask_about_conflict(result.conflicts[0])

    def _ask_about_conflict(self, conflict: Conflict) -> None:
        dialog = ConflictDialog(conflict, self)
        if dialog.exec() and dialog.choice is not None:
            self.resolve_conflict(conflict, dialog.choice)

    def resolve_conflict(self, conflict: Conflict, choice: str) -> None:
        """Apply the user's ruling on a fight. One field, one undoable edit.

        Split from the dialog so tests can rule both ways without a window.
        """
        value = (
            conflict.challenger_value if choice == "challenger"
            else conflict.incumbent_value
        )
        section, name = conflict.field.split(".", 1)
        self._store.update_section(section, **{name: value})
        self._status_detail.setText(
            f"{conflict.field} settled at {value} - "
            f"[{conflict.challenger_rule}] vs [{conflict.incumbent_rule}] "
            f"resolved by you."
        )

    def design_for_job(self, travel_mm: float) -> Solution | None:
        """Derive the geometry from the job and apply it as one undoable step.

        Returns the solution so the caller can present the reasoning, or None
        when there is no travel to design for. Split from `on_design` so tests
        can exercise the pipeline without a dialog to dismiss.
        """
        if travel_mm <= 0.0:
            return None
        cfg = self._store.config

        # Probe how many modules across the symbol will be for the digits this
        # travel needs, so the solver sizes the right matrix.
        digits = max(cfg.payload.digits, len(str(int(max(travel_mm, 1.0)))))
        sample = cfg.payload.prefix + "0" * digits + cfg.payload.suffix
        cols = probe_matrix_cols(self._controller.cache, cfg.symbol.symbology, sample)

        solution = solve(cfg, travel_mm=travel_mm, matrix_cols=cols)
        self._store.set_config(solution.config)
        return solution

    @Slot()
    def on_design(self) -> None:
        travel = self._job_bar.travel_spin.value()
        solution = self.design_for_job(travel)
        if solution is None:
            QMessageBox.information(
                self, "Design strip",
                "Enter the axis travel first - it is the one dimension the "
                "design starts from.",
            )
            return

        lines = [d.reason for d in solution.decisions]
        if solution.problems:
            text = (
                "The job as stated cannot be fully satisfied:\n\n"
                + "\n\n".join(f"* {p}" for p in solution.problems)
                + "\n\nBest available design applied anyway:\n\n"
                + "\n\n".join(lines)
            )
            QMessageBox.warning(self, "Design strip", text)
        else:
            QMessageBox.information(
                self, "Design strip",
                "Geometry derived from the job. Ctrl+Z restores the previous "
                "values.\n\n" + "\n\n".join(lines),
            )
        self._status_detail.setText(
            f"Designed from the job: {len(solution.decisions)} values derived."
        )

    @Slot(float)
    def _on_travel_requested(self, travel: float) -> None:
        """Turn an axis length into an index range.

        The conversion needs the resolved cell, so it needs the derived geometry.
        When the geometry is unresolved there is nothing sensible to compute -
        the pitch itself may be the thing that is wrong - so the request is
        dropped rather than guessed at.
        """
        derived = self._controller.derived
        if derived is None:
            return
        pos = self._store.config.position
        end = end_index_for_travel(travel, pos, derived.cell)
        if end != pos.end_index:
            self._store.update_section("position", end_index=end)
        else:
            # No change to commit, so no configChanged to refresh the bar - but
            # the box may hold a number the range does not achieve, and leaving
            # it there would misreport the strip.
            self._job_bar.update_from(self._store.config, derived)

    # -- controller signals -------------------------------------------------

    @Slot(object)
    def _on_config_changed(self, cfg: AopsConfig, _changed: object) -> None:
        derived = self._controller.derived
        for panel in self._panels.values():
            panel.refresh(cfg, derived)
        self._act_undo.setEnabled(self._store.can_undo)
        self._act_redo.setEnabled(self._store.can_redo)

    @Slot(object)
    def _on_derived(self, derived: DerivedGeometry | None) -> None:
        cfg = self._store.config
        for panel in self._panels.values():
            panel.refresh(cfg, derived)
        self._parameter_summary.update_from(cfg, derived, self._controller.fingerprint)
        self._engineering_summary.update_from(cfg, derived)
        self._job_bar.update_from(cfg, derived)

        if derived is not None:
            self._status_pages.setText(
                f"{derived.total_pdf_pages} pages   {derived.code_count} codes   "
                f"{derived.total_length_mm / 1000:.3f} m"
            )
        else:
            self._status_pages.setText("geometry unresolved")

    @Slot(object)
    def _on_validation(self, report: ValidationReport) -> None:
        self._pill.set_report(report)
        self._issues.set_report(report)

        for panel in self._panels.values():
            panel.apply_validation(report)
        self._job_bar.apply_validation(report)

        # Badge a header from the fields its own panel actually shows, not from
        # the config section it is named after. Design edits output.* and
        # printing.* fields, so keying on the name would badge "Output options"
        # for a warning whose control sits in "Design".
        for key, section in self._accordion.sections().items():
            panel = self._panels.get(key)
            paths = set(panel.rows()) if panel is not None else set()
            findings = [f for f in report.findings if f.field in paths]
            worst = max((f.severity for f in findings), default=None)
            section.set_severity(worst, len(findings))

        blocked = report.blocks_export
        self._act_export.setEnabled(not blocked)
        self._act_export_cont.setEnabled(not blocked)
        self._act_export_rows.setEnabled(not blocked)
        self._act_test_page.setEnabled(not blocked)

        if blocked:
            ids = ", ".join(sorted({f.rule_id for f in report.blocking}))
            tip = f"Export blocked by: {ids}"
            self._act_export.setToolTip(tip)
            self._act_export_cont.setToolTip(tip)
            worst_finding = max(report.blocking, key=lambda f: f.severity)
            self._status_detail.setText(f"[{worst_finding.rule_id}] {worst_finding.message}")
        else:
            self._act_export.setToolTip("Export tiled sheets.")
            self._act_export_cont.setToolTip("Export the continuous single-page strip.")
            warnings = [f for f in report.findings if f.severity == Severity.WARNING]
            self._status_detail.setText(
                f"Ready to export. {len(warnings)} warning(s)." if warnings else "Ready to export."
            )

    # -- presets ------------------------------------------------------------

    def _rebuild_presets_menu(self) -> None:
        menu = self._presets_menu
        menu.clear()

        # Ungrouped presets first, then one submenu per group, so a family like
        # the code sizes does not bury everything else.
        groups: dict[str, QMenu] = {}
        for preset in BUILT_IN_PRESETS:
            target = menu
            if preset.group:
                submenu = groups.get(preset.group)
                if submenu is None:
                    submenu = groups[preset.group] = menu.addMenu(preset.group)
                    submenu.setToolTipsVisible(True)
                target = submenu
            action = target.addAction(preset.name)
            action.setToolTip(preset.description)
            action.triggered.connect(lambda _c=False, p=preset: self._apply_preset(p))

        saved = self._settings.list_presets()
        if saved:
            menu.addSeparator()
            for path in saved:
                action = menu.addAction(path.stem)
                action.triggered.connect(lambda _c=False, p=path: self._apply_preset_file(p))

        menu.addSeparator()
        menu.addAction("Save current settings as preset...", self.on_save_preset)
        if saved:
            remove = menu.addMenu("Delete preset")
            for path in saved:
                remove.addAction(path.stem, lambda p=path: self._delete_preset(p))

    def _apply_preset(self, preset: Preset) -> None:
        """Apply a preset as one undoable step."""
        self._store.set_config(apply_preset(preset, self._store.config))
        self._status_detail.setText(
            f"Applied preset '{preset.name}' - {preset.field_count} settings. "
            f"Machine, strip ID and index range unchanged."
        )

    def _apply_preset_file(self, path: Path) -> None:
        try:
            self._apply_preset(load_preset(path.read_text(encoding="utf-8")))
        except (AopsError, OSError) as exc:
            QMessageBox.warning(self, "Could not open preset", str(exc))

    def _delete_preset(self, path: Path) -> None:
        confirm = QMessageBox.question(
            self,
            "Delete preset",
            f"Delete the preset '{path.stem}'?\n\nThis cannot be undone.",
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._settings.delete_preset(path)

    def on_save_preset(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "Save preset",
            "Name for this preset:\n\n"
            "It will store the geometry, design, paper, printing, media, printer\n"
            "and reader settings - but not the machine name, strip ID, revision\n"
            "or index range, which belong to this strip alone.",
        )
        if not ok or not name.strip():
            return
        preset = capture_preset(self._store.config, name.strip())
        try:
            path = self._settings.save_preset(preset.name, dump_preset(preset, app_version=__version__))
        except OSError as exc:
            QMessageBox.warning(self, "Could not save preset", str(exc))
            return
        self._status_detail.setText(f"Saved preset '{preset.name}' to {path}")

    @Slot(object)
    def _apply_fix(self, fix: object) -> None:
        """Apply a correction offered by a validation finding.

        Goes through the store like any other edit, so it lands on the undo
        stack as one step and the user can back it out with Ctrl+Z if the
        suggestion was not what they meant.
        """
        field = getattr(fix, "field", None)
        if not field or "." not in field:
            return
        section, name = field.split(".", 1)
        self._store.update_section(section, **{name: fix.value})
        self._focus_field(field)

    # -- simple / advanced --------------------------------------------------

    def _restore_mode(self) -> None:
        """Apply the remembered mode once the panels are built."""
        stored = self._settings.ui_mode()
        mode = UiLevel.SIMPLE if stored == UiLevel.SIMPLE.name else UiLevel.ADVANCED
        self._mode = mode
        self._apply_visibility()

    def _toggle_mode(self) -> None:
        self._set_mode(
            UiLevel.ADVANCED if self._mode is UiLevel.SIMPLE else UiLevel.SIMPLE
        )

    @Slot(object)
    def _set_mode(self, mode: UiLevel) -> None:
        """Switch how much of the configuration is on show, and remember it."""
        if mode is self._mode:
            self._accordion.show_mode(mode, self._hidden_field_count())
            return
        self._mode = mode
        self._settings.set_ui_mode(mode.name)
        self._apply_visibility()

    def _hidden_field_count(self) -> int:
        total = sum(len(p.rows()) for p in self._panels.values())
        simple = sum(p.simple_row_count() for p in self._panels.values())
        return total - simple

    def _apply_visibility(self) -> None:
        """Re-apply mode and filter together, and hide emptied sections."""
        needle = self._accordion.filter_text()
        for key, section in self._accordion.sections().items():
            panel = self._panels.get(key)
            if panel is None:
                continue
            shown = panel.refresh_visibility(needle, self._mode)
            section.set_visible_for_filter(shown > 0)
            if needle.strip():
                section.set_expanded(shown > 0)

        self._accordion.renumber_visible()
        self._accordion.show_mode(self._mode, self._hidden_field_count())

        # A search that matches only hidden fields would otherwise look like the
        # setting had been removed from the application.
        if needle.strip() and self._mode is UiLevel.SIMPLE:
            hidden_hits = sum(
                1
                for panel in self._panels.values()
                for path, row in panel.rows().items()
                if row.matches(needle.strip().lower()) and not visible_at(path, self._mode)
            )
            self._accordion.flag_hidden_match(hidden_hits)

    @Slot(str)
    def _on_filter_changed(self, needle: str) -> None:
        """Show only sections containing a matching field.

        A filtered section is force-expanded so its matches are actually
        visible; clearing the filter restores whatever the user had open, so
        searching for something does not quietly rearrange the panel.
        """
        active = bool(needle.strip())
        if active and self._expanded_before_filter is None:
            self._expanded_before_filter = {
                key: section.is_expanded()
                for key, section in self._accordion.sections().items()
            }

        self._apply_visibility()

        if not active and self._expanded_before_filter is not None:
            for key, was_open in self._expanded_before_filter.items():
                section = self._accordion.section(key)
                if section is not None:
                    section.set_expanded(was_open)
            self._expanded_before_filter = None

    @Slot(object)
    def _on_preview(self, draw_list: DrawList) -> None:
        self._preview.set_draw_list(draw_list)

    @Slot(object)
    def _on_overview(self, draw_list: DrawList) -> None:
        self._overview.set_draw_list(draw_list)

    @Slot(str)
    def _on_error(self, message: str) -> None:
        self._status_detail.setText(message)

    def _focus_field(self, path: str) -> None:
        """Expand the section that actually owns the control, and focus it.

        Found by asking the panels which one holds the row, not by splitting the
        config path. Design edits output.* and printing.* fields, so keying off
        the prefix expanded "Print" for a finding whose control sits in
        "Design" - and then focused a widget that was still hidden.

        Switches to Advanced first if the field is not in the Simple set,
        otherwise activating a blocking finding from Simple mode would appear to
        do nothing at all. The job bar is checked before that, because switching
        modes to reach a box that was on screen the whole time would be worse
        than not switching at all.
        """
        if self._job_bar.focus_field(path):
            return

        if not visible_at(path, self._mode):
            self._set_mode(UiLevel.ADVANCED)

        for key, panel in self._panels.items():
            if path not in panel.rows():
                continue
            section = self._accordion.section(key)
            if section is not None:
                section.set_visible_for_filter(True)
                section.set_expanded(True)
            panel.focus_field(path)
            return

    # -- actions ------------------------------------------------------------

    def on_new(self) -> None:
        if not self._confirm_discard():
            return
        self._store.set_config(AopsConfig(), mark_clean=True)
        self._store.set_path(None)
        self._controller.recompute()

    def on_open(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", self._settings.last_project_dir(), PROJECT_FILTER
        )
        if not path:
            return
        try:
            loaded = load_project(Path(path).read_text(encoding="utf-8"))
        except (AopsError, OSError) as exc:
            QMessageBox.critical(self, "Cannot open project", str(exc))
            return

        self._store.set_config(loaded.config, mark_clean=True)
        self._store.set_path(path)
        self._settings.set_last_project_dir(str(Path(path).parent))
        self._settings.push_recent(path)
        self._controller.recompute()

        if loaded.warnings:
            QMessageBox.information(self, "Project opened", "\n".join(loaded.warnings))

    def on_save(self) -> None:
        path = self._store.path
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save project", self._settings.last_project_dir(), PROJECT_FILTER
            )
            if not path:
                return
            if not path.endswith(PROJECT_FILE_SUFFIX):
                path += PROJECT_FILE_SUFFIX
        try:
            Path(path).write_text(
                dump_project(self._store.config, app_version=__version__), encoding="utf-8"
            )
        except OSError as exc:
            QMessageBox.critical(self, "Cannot save project", str(exc))
            return

        self._store.set_path(path)
        self._store.mark_saved()
        self._settings.set_last_project_dir(str(Path(path).parent))
        self._settings.push_recent(path)
        self._status_detail.setText(f"Saved {path}")

    def on_export_tiles(self) -> None:
        self._start_export(tiles=True, continuous=False, rows=1)

    def multirow_rows(self) -> int:
        """Row count the Multi-Row export will use, resolved from the setting.

        The Output panel's rows-per-sheet field tunes it; the default of 1
        means "unset" for this purpose - a user pressing Export Multi-Row with
        the field untouched plainly wants stacking, so it fills the sheet.
        """
        rows = self._store.config.output.rows_per_sheet
        return 0 if rows == 1 else rows

    def on_export_multirow(self) -> None:
        rows = self.multirow_rows()
        if not self._confirm_multirow(rows):
            return
        self._start_export(tiles=True, continuous=False, rows=rows)

    def _confirm_multirow(self, rows: int) -> bool:
        """True when Multi-Row will actually stack, or the user accepts that
        it cannot.

        Learned from the first real multi-row print: a 55 mm band on A4
        landscape fits exactly one row, so auto-fill quietly reproduced the
        classic single-row sheets and the export looked broken. When stacking
        is impossible, say so - with the numbers and the way out - instead of
        exporting a duplicate of Export PDF without comment.
        """
        cfg = self._store.config
        with_cal = cfg.output.calibration_bar
        effective = rows if rows else rows_that_fit(cfg, with_calibration=with_cal)
        if effective > 1:
            return True
        two = solve_sheet_bands(cfg, 2, with_calibration=with_cal).total_height_mm
        usable = cfg.paper.usable_height_mm()
        answer = QMessageBox.question(
            self,
            "Multi-Row cannot stack",
            f"Only one strip row fits this sheet, so Multi-Row would print "
            f"exactly the same pages as Export PDF.\n\n"
            f"Two rows of the current geometry "
            f"({cfg.dimensions.strip_height_mm:.0f} mm band plus ruler and "
            f"caption) need {two:.0f} mm of sheet height; {usable:.0f} mm is "
            f"usable.\n\n"
            f"To stack rows, shrink the job first: Design strip derives the "
            f"smallest geometry the scanner still reads reliably - typically "
            f"a 20 mm band that stacks three or more rows per sheet.\n\n"
            f"Export the single-row sheets anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def on_export_continuous(self) -> None:
        self._start_export(tiles=False, continuous=True)

    def on_help(self) -> None:
        HelpDialog(self).exec()

    def on_about(self) -> None:
        AboutDialog(self).exec()

    # -- export -------------------------------------------------------------

    def _start_export(
        self, *, tiles: bool, continuous: bool, rows: int | None = None
    ) -> None:
        import dataclasses

        derived = self._controller.derived
        if derived is None:
            QMessageBox.warning(self, "Cannot export", "The geometry could not be resolved.")
            return

        # Snapshot with only the requested outputs enabled. Frozen dataclass, so
        # the worker thread cannot see it change underneath it. `rows` pins the
        # sheet layout for this run: Export PDF always passes 1 so the classic
        # single-row layout stays what that button has always produced, and the
        # Multi-Row action passes 0 (fill) or the configured count.
        cfg = self._store.config
        output = dataclasses.replace(
            cfg.output, tiled_pages=tiles, continuous=continuous
        )
        basename = "barcode_strip"
        if rows is not None:
            output = dataclasses.replace(output, rows_per_sheet=rows)
            if rows != 1:
                basename = "barcode_strip_multirow"
        cfg = dataclasses.replace(cfg, output=output)
        self._launch_export(cfg, derived, basename)

    def coupon_config(self) -> AopsConfig | None:
        """The current job, trimmed to the single sheet a bench test needs.

        Same geometry, same payloads, same paper - the first page of the real
        strip, so what the bench proves is what the machine gets. Only the
        range is shortened (to one page of codes), the guide page dropped, and
        the output forced to one tiled sheet. The live configuration is not
        touched; the coupon exists only for the export.
        """
        import dataclasses

        derived = self._controller.derived
        if derived is None or not derived.pages:
            return None
        cfg = self._store.config
        pos = cfg.position

        # Start from what the full pagination says the first page carries, then
        # let pagination itself confirm. Estimating from cells-per-page ignored
        # the leader; trusting the first page's last code ignored the trailer,
        # which follows the final code and spilled onto a second sheet. Only
        # the paginator knows where its own furniture lands, so ask it until
        # it answers "one page" - a couple of iterations at most.
        end = min(pos.end_index, derived.pages[0].last_index or pos.end_index)
        while True:
            coupon = dataclasses.replace(
                cfg,
                position=dataclasses.replace(pos, end_index=end),
                output=dataclasses.replace(
                    cfg.output, tiled_pages=True, continuous=False,
                    instruction_page=False,
                ),
            )
            if end <= pos.start_index:
                return coupon
            try:
                pages = len(derive(coupon, matrix_cols=derived.matrix_cols).pages)
            except AopsError:
                return coupon
            if pages <= 1:
                return coupon
            end -= pos.increment

    def on_export_test_page(self) -> None:
        """Export the one-sheet bench coupon: calibration bar plus real codes.

        The freeze checklist's step six, made one click: print this, measure
        the bar, scan the codes at the real mounting distance - before
        committing a full roll to a setup nobody has proven.
        """
        coupon = self.coupon_config()
        if coupon is None:
            QMessageBox.warning(self, "Cannot export", "The geometry could not be resolved.")
            return
        sample = coupon.payload.prefix + "0" * coupon.payload.digits + coupon.payload.suffix
        cols = probe_matrix_cols(self._controller.cache, coupon.symbol.symbology, sample)
        try:
            derived = derive(coupon, matrix_cols=cols)
        except AopsError as exc:
            QMessageBox.warning(self, "Cannot export", str(exc))
            return
        self._launch_export(coupon, derived, "test_page")

    def _launch_export(self, cfg: AopsConfig, derived: DerivedGeometry, basename: str) -> None:
        if self._thread is not None:
            return

        directory = QFileDialog.getExistingDirectory(
            self, "Choose output folder", self._settings.last_export_dir()
        )
        if not directory:
            return
        self._settings.set_last_export_dir(directory)

        self._progress = ExportProgressDialog(self)
        self._thread = QThread(self)
        self._worker = ExportWorker(
            cfg, derived, self._controller.cache, Path(directory), basename
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.finished.connect(self._on_export_finished)
        self._worker.failed.connect(self._on_export_failed)
        self._worker.cancelled.connect(self._on_export_cancelled)
        self._progress.cancelRequested.connect(self._worker.cancel)

        self._act_export.setEnabled(False)
        self._act_export_cont.setEnabled(False)
        self._thread.start()
        self._progress.exec()

    def _cleanup_export(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread = None
        self._worker = None
        if self._progress is not None:
            self._progress.accept()
            self._progress = None
        self._act_export.setEnabled(True)
        self._act_export_cont.setEnabled(True)

    @Slot(list)
    def _on_export_finished(self, paths: list) -> None:
        self._cleanup_export()
        names = "\n".join(paths)
        self._status_detail.setText(f"Exported {len(paths)} file(s)")
        QMessageBox.information(self, "Export complete", f"Wrote:\n{names}")

    @Slot(str)
    def _on_export_failed(self, message: str) -> None:
        self._cleanup_export()
        QMessageBox.critical(self, "Export failed", message)

    @Slot()
    def _on_export_cancelled(self) -> None:
        self._cleanup_export()
        self._status_detail.setText("Export cancelled; partial files removed.")

    # -- window state -------------------------------------------------------

    def _update_title(self) -> None:
        name = Path(self._store.path).name if self._store.path else "untitled"
        dirty = "*" if self._store.dirty else ""
        self.setWindowTitle(f"{name}{dirty} - {__app_name__}")

    def _confirm_discard(self) -> bool:
        if not self._store.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "The current project has unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    def _restore_window(self) -> None:
        geometry = self._settings.window_geometry()
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(1520, 950)
        state = self._settings.window_state()
        if state:
            self.restoreState(state)
        splitter = self._settings.splitter_state()
        if splitter:
            self._splitter.restoreState(splitter)
        self._update_title()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self._confirm_discard():
            event.ignore()
            return
        self._settings.save_window(
            self.saveGeometry(), self.saveState(), self._splitter.saveState()
        )
        self._settings.sync()
        if self._worker is not None:
            self._worker.cancel()
        self._cleanup_export()
        super().closeEvent(event)
