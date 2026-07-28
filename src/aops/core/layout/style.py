"""Print styles.

Deliberately separate from `ui/theme`. The PDF is pure black on white whatever
the application's dark UI looks like, and the preview shows the *print* palette
on a white page floating on dark chrome - so an engineer sees what will come out
of the printer, not a dark-mode approximation of it.
"""

from __future__ import annotations

from aops.core.drawlist import BLACK, LIGHT_GREY, MID_GREY, WHITE, Style, TextStyle
from aops.core.enums import FontRole, LineCap

# Line weights, in mm.
HAIRLINE_MM = 0.10
THIN_MM = 0.18
NORMAL_MM = 0.25
THICK_MM = 0.45
HEAVY_MM = 0.70

INK = BLACK
PAPER = WHITE

# ---------------------------------------------------------------- geometry --

SYMBOL_FILL = Style(stroke=None, fill=INK, line_width_mm=0.0)
STRIP_OUTLINE = Style(stroke=MID_GREY, fill=None, line_width_mm=HAIRLINE_MM)
PAGE_FILL = Style(stroke=None, fill=PAPER)

RULER_MINOR = Style(stroke=INK, line_width_mm=HAIRLINE_MM, cap=LineCap.BUTT)
RULER_MEDIUM = Style(stroke=INK, line_width_mm=THIN_MM)
RULER_MAJOR = Style(stroke=INK, line_width_mm=NORMAL_MM)
RULER_EMPHASIS = Style(stroke=INK, line_width_mm=THICK_MM)
RULER_BASELINE = Style(stroke=INK, line_width_mm=THIN_MM)

CALIBRATION_BAR = Style(stroke=INK, fill=None, line_width_mm=THICK_MM)
CALIBRATION_TICK = Style(stroke=INK, line_width_mm=THICK_MM)

CUT_MARK = Style(stroke=INK, line_width_mm=THIN_MM)
CUT_LINE = Style(stroke=LIGHT_GREY, line_width_mm=HAIRLINE_MM, dash_mm=(2.0, 2.0))
REGISTRATION = Style(stroke=INK, line_width_mm=THIN_MM)
ARROW = Style(stroke=INK, fill=INK, line_width_mm=THIN_MM)

RULE_LINE = Style(stroke=INK, line_width_mm=THIN_MM)
FAINT_RULE = Style(stroke=LIGHT_GREY, line_width_mm=HAIRLINE_MM)

OVERVIEW_PAGE = Style(stroke=MID_GREY, fill=None, line_width_mm=HAIRLINE_MM)
OVERVIEW_DENSITY = Style(stroke=None, fill=LIGHT_GREY)
OVERVIEW_SPLICE = Style(stroke=INK, line_width_mm=THIN_MM)
OVERVIEW_HIGHLIGHT = Style(stroke=(0.10, 0.45, 0.80), fill=None, line_width_mm=NORMAL_MM)

# ------------------------------------------------------------------- text --

HUMAN_READABLE = TextStyle(role=FontRole.MONO, size_pt=7.0, fill=INK)
RULER_LABEL = TextStyle(role=FontRole.MONO, size_pt=6.0, fill=INK)
HEADER_TITLE = TextStyle(role=FontRole.SANS_BOLD, size_pt=10.0, fill=INK)
HEADER_FIELD = TextStyle(role=FontRole.MONO, size_pt=7.0, fill=INK)
FOOTER = TextStyle(role=FontRole.MONO, size_pt=6.5, fill=INK)
CALIBRATION_LABEL = TextStyle(role=FontRole.MONO_BOLD, size_pt=8.0, fill=INK)
CALIBRATION_WARNING = TextStyle(role=FontRole.SANS_BOLD, size_pt=9.0, fill=INK)
CALIBRATION_HINT = TextStyle(role=FontRole.MONO, size_pt=6.5, fill=INK)

GUIDE_TITLE = TextStyle(role=FontRole.SANS_BOLD, size_pt=16.0, fill=INK)
GUIDE_HEADING = TextStyle(role=FontRole.SANS_BOLD, size_pt=9.5, fill=INK)
GUIDE_BODY = TextStyle(role=FontRole.SANS, size_pt=8.0, fill=INK)
GUIDE_MONO = TextStyle(role=FontRole.MONO, size_pt=7.5, fill=INK)
GUIDE_WARNING = TextStyle(role=FontRole.SANS_BOLD, size_pt=8.5, fill=INK)

OVERVIEW_LABEL = TextStyle(role=FontRole.MONO, size_pt=5.0, fill=INK)
