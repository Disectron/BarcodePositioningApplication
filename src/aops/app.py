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
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, False)
    app = create_app(argv)

    from aops.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
