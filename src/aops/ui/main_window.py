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
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from aops import __app_name__, __version__
from aops.controller.app_controller import AppController
from aops.controller.config_store import ConfigStore
from aops.controller.workers import ExportWorker
from aops.core.config import AopsConfig
from aops.core.drawlist import DrawList
from aops.core.enums import Severity
from aops.core.errors import AopsError
from aops.core.project_io import (
    PROJECT_FILE_SUFFIX,
    dump_project,
    load_project,
)
from aops.core.stats import DerivedGeometry
from aops.core.validation import ValidationReport
from aops.ui.dialogs.about_dialog import AboutDialog, HelpDialog
from aops.ui.dialogs.export_progress import ExportProgressDialog
from aops.ui.panels.sections import PANEL_SPECS
from aops.ui.settings_store import SettingsStore
from aops.ui.widgets.accordion import AccordionPanel
from aops.ui.widgets.issues_panel import IssuesPanel, StatusPill
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
        self._issues = IssuesPanel(self._tabs)

        for widget, title in (
            (self._parameter_summary, "Parameter summary"),
            (self._engineering_summary, "Engineering summary"),
            (self._issues, "Issues"),
        ):
            scroll = QScrollArea(self._tabs)
            scroll.setWidget(widget)
            scroll.setWidgetResizable(True)
            self._tabs.addTab(scroll, title)

        self._tabs.setMinimumHeight(220)
        right_layout.addWidget(self._tabs, 2)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([400, 1000])

        self.setCentralWidget(splitter)

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main", self)
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
        bar.addSeparator()
        self._act_undo = add("Undo", self._store.undo, "Ctrl+Z")
        self._act_redo = add("Redo", self._store.redo, "Ctrl+Y")
        bar.addSeparator()
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

        for key, section in self._accordion.sections().items():
            findings = report.for_section(key)
            worst = max((f.severity for f in findings), default=None)
            section.set_severity(worst, len(findings))

        blocked = report.blocks_export
        self._act_export.setEnabled(not blocked)
        self._act_export_cont.setEnabled(not blocked)

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

        for key, section in self._accordion.sections().items():
            panel = self._panels.get(key)
            if panel is None:
                continue
            matches = panel.apply_filter(needle)
            section.set_visible_for_filter(matches > 0 or not active)
            if active:
                section.set_expanded(matches > 0)

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
        """Expand the owning section and focus the offending control."""
        section_key = path.split(".", 1)[0]
        section = self._accordion.section(section_key)
        if section is not None:
            section.set_expanded(True)
        for panel in self._panels.values():
            if panel.focus_field(path):
                break

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
        self._start_export(tiles=True, continuous=False)

    def on_export_continuous(self) -> None:
        self._start_export(tiles=False, continuous=True)

    def on_help(self) -> None:
        HelpDialog(self).exec()

    def on_about(self) -> None:
        AboutDialog(self).exec()

    # -- export -------------------------------------------------------------

    def _start_export(self, *, tiles: bool, continuous: bool) -> None:
        import dataclasses

        derived = self._controller.derived
        if derived is None:
            QMessageBox.warning(self, "Cannot export", "The geometry could not be resolved.")
            return
        if self._thread is not None:
            return

        directory = QFileDialog.getExistingDirectory(
            self, "Choose output folder", self._settings.last_export_dir()
        )
        if not directory:
            return
        self._settings.set_last_export_dir(directory)

        # Snapshot with only the requested outputs enabled. Frozen dataclass, so
        # the worker thread cannot see it change underneath it.
        cfg = self._store.config
        cfg = dataclasses.replace(
            cfg,
            output=dataclasses.replace(cfg.output, tiled_pages=tiles, continuous=continuous),
        )

        self._progress = ExportProgressDialog(self)
        self._thread = QThread(self)
        self._worker = ExportWorker(
            cfg, derived, self._controller.cache, Path(directory), "barcode_strip"
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
