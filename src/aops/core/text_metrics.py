"""Text measurement without a rendering backend.

Layout needs to centre and right-align strings before either Qt or ReportLab is
involved. `TextMeasurer` is the seam; each backend can supply a precise
implementation, and `MonospaceMetrics` is the fallback.

The fallback is exact rather than approximate for this application, because
every measured string here - indices, distances, page numbers, code ranges - is
deliberately set in a monospaced face. Proportional text (the guide page prose)
is only ever left-aligned, where the measurement does not matter.
"""

from __future__ import annotations

from typing import Protocol

from aops.core.enums import FontRole
from aops.core.units import mm_to_pt


class TextMeasurer(Protocol):
    """Measures the advance width of a string, in millimetres."""

    def width_mm(self, text: str, role: FontRole, size_pt: float) -> float: ...


class MonospaceMetrics:
    """Advance-width model for monospaced faces.

    0.60 em is the advance of DejaVu Sans Mono, Consolas and Courier alike, so
    for the fixed-width strings this application measures the result is exact.
    """

    #: Advance width as a fraction of the em size, per role.
    ADVANCE = {
        FontRole.MONO: 0.60,
        FontRole.MONO_BOLD: 0.60,
        FontRole.SANS: 0.52,
        FontRole.SANS_BOLD: 0.55,
    }

    def width_mm(self, text: str, role: FontRole, size_pt: float) -> float:
        advance = self.ADVANCE.get(role, 0.60)
        return len(text) * size_pt * advance / mm_to_pt(1.0)

    def height_mm(self, size_pt: float) -> float:
        """Cap height plus descender, a usable proxy for line height."""
        return size_pt * 1.2 / mm_to_pt(1.0)


#: Shared default instance; stateless, so sharing is safe.
DEFAULT_METRICS = MonospaceMetrics()
