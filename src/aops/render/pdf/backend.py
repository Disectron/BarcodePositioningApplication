"""ReportLab implementation of the `Painter` protocol.

Coordinate handling is the only subtle part. Draw lists are in design
millimetres with Y increasing downward; PDF is in points with Y increasing
upward. Rather than converting every coordinate, the canvas transform is set up
once so the backend can draw directly in design millimetres.

THE TRAP THAT COMES WITH IT: the transform uses a negative Y scale, which
mirrors glyphs. Every `Text` primitive therefore has to locally undo the flip.
This is written down because it is invisible until you look at the output and
the text is backwards.
"""

from __future__ import annotations

from aops.core.drawlist import Line, PolyLine, Rect, Style, SymbolPrim, Text
from aops.core.enums import Anchor, LineCap
from aops.core.matrix import to_rects
from aops.core.units import MM2PT
from aops.render.pdf.fonts import pdf_font

_CAPS = {LineCap.BUTT: 0, LineCap.ROUND: 1, LineCap.SQUARE: 2}


class PdfPainter:
    """Draws a `DrawList` onto a ReportLab canvas.

    The caller is responsible for establishing the transform (see
    `export.begin_content`); the painter assumes it can draw in design mm with
    Y running downward.
    """

    def __init__(self, canvas, rect_cache=None) -> None:  # type: ignore[no-untyped-def]
        self._c = canvas
        self._rect_cache = rect_cache

    # -- Painter protocol ---------------------------------------------------

    def begin(self, width_mm: float, height_mm: float) -> None:
        self._width_mm = width_mm
        self._height_mm = height_mm

    def end(self) -> None:
        pass

    def rect(self, prim: Rect) -> None:
        self._apply(prim.style)
        stroke = 1 if prim.style.stroke else 0
        fill = 1 if prim.style.fill else 0
        if not stroke and not fill:
            return
        self._c.rect(prim.x, prim.y, prim.w, prim.h, stroke=stroke, fill=fill)

    def line(self, prim: Line) -> None:
        if not prim.style.stroke:
            return
        self._apply(prim.style)
        self._c.line(prim.x1, prim.y1, prim.x2, prim.y2)

    def polyline(self, prim: PolyLine) -> None:
        if len(prim.pts) < 2:
            return
        self._apply(prim.style)
        path = self._c.beginPath()
        path.moveTo(*prim.pts[0])
        for x, y in prim.pts[1:]:
            path.lineTo(x, y)
        if prim.close:
            path.close()
        self._c.drawPath(
            path,
            stroke=1 if prim.style.stroke else 0,
            fill=1 if prim.style.fill else 0,
        )

    def text(self, prim: Text) -> None:
        c = self._c
        c.saveState()
        c.setFillColorRGB(*prim.style.fill)
        c.setFont(pdf_font(prim.style.role), prim.style.size_pt)
        c.translate(prim.x, prim.y)
        # Undo the enclosing Y flip so glyphs are not mirrored. This applies to
        # glyphs only; all positioning above is still in design space.
        c.scale(1, -1)
        if prim.rotation_deg:
            c.rotate(-prim.rotation_deg)

        # The enclosing transform makes one user unit equal k*MM2PT points, so a
        # font size given in points would come out MM2PT times too large.
        # Dividing by MM2PT leaves the glyph size at size_pt * k, which is
        # correct: text must scale with the printer compensation like everything
        # else on the sheet.
        c.scale(1.0 / MM2PT, 1.0 / MM2PT)

        if prim.anchor is Anchor.BASELINE_CENTRE:
            c.drawCentredString(0, 0, prim.text)
        elif prim.anchor is Anchor.BASELINE_RIGHT:
            c.drawRightString(0, 0, prim.text)
        else:
            c.drawString(0, 0, prim.text)
        c.restoreState()

    def symbol(self, prim: SymbolPrim) -> None:
        """Draw a symbol as vector rectangles.

        Vector rather than raster is the whole reason the symbol layer recovers
        a module matrix: these rectangles are exact at any RIP resolution, where
        an embedded bitmap would be resampled and its module edges softened.
        """
        matrix = prim.matrix
        if matrix.cols == 0 or matrix.rows == 0:
            return
        module = prim.size_mm / matrix.cols

        rects = (
            self._rect_cache.rects(matrix) if self._rect_cache is not None else to_rects(matrix)
        )

        c = self._c
        c.saveState()
        c.setFillColorRGB(0, 0, 0)
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(0)
        for col, row, w, h in rects:
            c.rect(
                prim.x + col * module,
                prim.y + row * module,
                w * module,
                h * module,
                stroke=0,
                fill=1,
            )
        c.restoreState()

    # -- internals ----------------------------------------------------------

    def _apply(self, style: Style) -> None:
        c = self._c
        if style.stroke:
            c.setStrokeColorRGB(*style.stroke)
        if style.fill:
            c.setFillColorRGB(*style.fill)
        c.setLineWidth(style.line_width_mm)
        c.setLineCap(_CAPS.get(style.cap, 0))
        if style.dash_mm:
            c.setDash(list(style.dash_mm))
        else:
            c.setDash([])
