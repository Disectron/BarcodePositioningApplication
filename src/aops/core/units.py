"""Unit conversion and the rounding policy that makes strip packing exact.

Everything the geometry engine packs is computed in **integer micrometres**.
This is deliberate and load-bearing, not fastidiousness: pagination asks
"does one more 25.000 mm cell fit into 275.0000000001 mm of usable width?"
thousands of times, and in binary floating point that question has no stable
answer. In integer micrometres it is decidable, which is what lets the splice
guarantee in `geometry.verify_splices` be *proved* rather than approximated.

Floats appear only at the emit boundary, where a PDF or a QPainter needs points
or pixels.

The two conversions below are asymmetric on purpose:

* `mm_to_um` **rounds** - it converts an *authored* dimension. The user typed
  25.0 and means exactly 25 000 um.
* `um_floor` **truncates** - it converts an available *capacity*. Never claim
  space you do not have; a half-micrometre of optimism becomes a symbol sliced
  in half by a guillotine.
"""

from __future__ import annotations

from math import floor

#: Points per millimetre (72 dpi / 25.4 mm per inch).
MM2PT: float = 72.0 / 25.4

#: Micrometres per millimetre.
UM_PER_MM: int = 1000

#: Millimetres per inch.
MM_PER_INCH: float = 25.4

#: Hard page-dimension ceiling in PDF 1.x: 14400 pt = 200 in = 5080 mm.
#: Exceeding this requires /UserUnit (PDF 1.6+) or the page is non-conformant.
PDF_MAX_PT: float = 14400.0

#: Largest /UserUnit value permitted by the PDF specification.
PDF_MAX_USER_UNIT: float = 75000.0


def mm_to_um(value_mm: float) -> int:
    """Convert an **authored** dimension in mm to integer micrometres (rounds)."""
    return round(value_mm * UM_PER_MM)


def um_floor(value_mm: float) -> int:
    """Convert an available **capacity** in mm to integer micrometres (truncates)."""
    return floor(value_mm * UM_PER_MM)


def um_to_mm(value_um: int) -> float:
    """Convert integer micrometres back to millimetres."""
    return value_um / UM_PER_MM


def mm_to_pt(value_mm: float) -> float:
    """Convert millimetres to PDF points."""
    return value_mm * MM2PT


def pt_to_mm(value_pt: float) -> float:
    """Convert PDF points to millimetres."""
    return value_pt / MM2PT


def um_to_pt(value_um: int) -> float:
    """Convert integer micrometres to PDF points."""
    return (value_um / UM_PER_MM) * MM2PT


def dots_per_mm(dpi: int) -> float:
    """Printer dots per millimetre for a given DPI."""
    return dpi / MM_PER_INCH


def mm_per_dot(dpi: int) -> float:
    """Size of a single printer dot in millimetres."""
    return MM_PER_INCH / dpi
