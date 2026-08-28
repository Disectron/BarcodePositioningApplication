"""Application bootstrap."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from aops import __app_name__, __version__
from aops.ui.theme.palette import apply_palette

THEME_QSS = Path(__file__).parent / "ui" / "theme" / "aops.qss"


def create_app(argv: list[str] | None = None) -> QApplication:
    """Create and style the QApplication."""
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("AOPS")

    # Fusion honours a custom palette consistently across platforms; the native
    # styles ignore parts of it and the window would end up half light-themed.
    app.setStyle("Fusion")
    apply_palette(app)

    if THEME_QSS.exists():
        app.setStyleSheet(THEME_QSS.read_text(encoding="utf-8"))

    return app


def main(argv: list[str] | None = None) -> int:
    """Launch the GUI."""
    from aops.runtime import install_crash_handler

    # A windowed .exe has no console; without this an unhandled exception
    # closes the app with no trace. Installed for source runs too - the log
    # is just as useful there.
    install_crash_handler()

    args = list(argv) if argv is not None else sys.argv
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, False)
    app = create_app(args)

    from aops.core.project_io import PROJECT_FILE_SUFFIX
    from aops.ui.main_window import MainWindow

    window = MainWindow()
    # A .aops path on the command line is how "Open with AOPS" and the
    # installer's file association reach us.
    project = next(
        (a for a in args[1:] if a.lower().endswith(PROJECT_FILE_SUFFIX) and Path(a).exists()),
        None,
    )
    if project is not None:
        window.open_project(project)

    # The packaged build's smoke test: constructing the full window proves Qt
    # platform plugins, the theme, fonts and every panel import survived
    # freezing - without needing a display or a click to close it.
    if "--selftest" in args[1:]:
        window.close()
        return 0

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
