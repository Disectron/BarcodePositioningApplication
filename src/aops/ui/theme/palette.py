"""Dark industrial palette.

Deliberately restrained. Reference points are Visual Studio, TwinCAT XAE and
TIA Portal: near-neutral greys, a single blue accent used only for focus and
selection, and severity colours that are the only saturated things on screen so
a warning cannot be missed.

This is the *screen* palette. It has nothing to do with the printed output,
which is always black on white - see `core/layout/style.py`.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

# Surfaces, darkest to lightest.
BG_DEEPEST = "#1a1c1f"  # window behind panels
BG_BASE = "#212429"  # panel background
BG_RAISED = "#282c32"  # group boxes, headers
BG_INPUT = "#1b1e22"  # editable fields
BG_HOVER = "#2f343b"
BG_SELECTED = "#123a5e"

# Lines.
BORDER = "#33383f"
BORDER_STRONG = "#454b54"

# Text.
TEXT = "#d4d7dc"
TEXT_DIM = "#8b929c"
TEXT_DISABLED = "#5a6069"
TEXT_HEADING = "#e8eaed"

# The single accent.
ACCENT = "#3c9ae8"
ACCENT_DIM = "#2b6f9e"

# Severity.
INFO = "#5aa9e6"
WARNING = "#e0a44a"
ERROR = "#e05c4a"
FATAL = "#f2506a"
OK = "#4bb37b"

# Preview canvas.
CANVAS_BG = "#15171a"
PAPER_WHITE = "#ffffff"


def apply_palette(app) -> None:  # type: ignore[no-untyped-def]
    """Apply the dark palette to a QApplication.

    Set alongside the stylesheet because some native controls (tooltips, text
    selection, disabled states) read QPalette directly and would otherwise stay
    light-themed.
    """
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_BASE))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_INPUT))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_RAISED))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(BG_RAISED))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(BG_RAISED))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_DISABLED))

    for group in (QPalette.ColorGroup.Disabled,):
        palette.setColor(group, QPalette.ColorRole.Text, QColor(TEXT_DISABLED))
        palette.setColor(group, QPalette.ColorRole.ButtonText, QColor(TEXT_DISABLED))
        palette.setColor(group, QPalette.ColorRole.WindowText, QColor(TEXT_DISABLED))

    app.setPalette(palette)


SEVERITY_COLOURS = {
    "INFO": INFO,
    "WARNING": WARNING,
    "ERROR": ERROR,
    "FATAL": FATAL,
}
