"""Qt implementation of the `Painter` protocol.

Draws the same `DrawList` the PDF backend draws, so the preview cannot disagree
with the export.

The one place the two backends deliberately differ is `symbol()`. The PDF always
emits vector rectangles because it is going to a printer. On screen, once a
module falls below a few pixels, blitting a cached image is both faster and
visually better than drawing dozens of sub-pixel rectangles that alias into
mush.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen

from aops.core.drawlist import Line, PolyLine, Rect, Style, SymbolPrim, Text
from aops.core.enums import Anchor, LineCap
from aops.core.matrix import to_rects
from aops.render.qt.fonts import qt_font

_CAPS = {
    LineCap.BUTT: Qt.PenCapStyle.FlatCap,
    LineCap.ROUND: Qt.PenCapStyle.RoundCap,
    LineCap.SQUARE: Qt.PenCapStyle.SquareCap,
}

#: Below this many device pixels per module, blit a cached image instead of
#: drawing individual rectangles.
RASTER_THRESHOLD_PX = 3.0


def _colour(rgb: tuple[float, float, float]) -> QColor:
    return QColor.fromRgbF(*rgb)


class QtPainter:
    """Draws a `DrawList` with a QPainter, in design millimetres."""

    def __init__(self, painter: QPainter, px_per_mm: float, image_cache=None) -> None:
        self._p = painter
        self._px_per_mm = px_per_mm
        self._image_cache = image_cache

    # -- Painter protocol ---------------------------------------------------

    def begin(self, width_mm: float, height_mm: float) -> None:
        self._p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    def end(self) -> None:
        pass

    def rect(self, prim: Rect) -> None:
        self._apply(prim.style)
        rect = QRectF(prim.x, prim.y, prim.w, prim.h)
        if prim.style.fill:
            self._p.fillRect(rect, QBrush(_colour(prim.style.fill)))
        if prim.style.stroke:
            self._p.drawRect(rect)

    def line(self, prim: Line) -> None:
        if not prim.style.stroke:
            return
        self._apply(prim.style)
        self._p.drawLine(QPointF(prim.x1, prim.y1), QPointF(prim.x2, prim.y2))

    def polyline(self, prim: PolyLine) -> None:
        if len(prim.pts) < 2:
            return
        self._apply(prim.style)
        path = QPainterPath(QPointF(*prim.pts[0]))
        for x, y in prim.pts[1:]:
            path.lineTo(QPointF(x, y))
        if prim.close:
            path.closeSubpath()
        if prim.style.fill:
            self._p.fillPath(path, QBrush(_colour(prim.style.fill)))
        if prim.style.stroke:
            self._p.strokePath(path, self._p.pen())

    def text(self, prim: Text) -> None:
        p = self._p
        p.save()
        p.translate(prim.x, prim.y)
        if prim.rotation_deg:
            p.rotate(prim.rotation_deg)

        # Fonts are sized in points; the painter is scaled to millimetres. Draw
        # the glyphs in a locally unscaled frame and scale back down, which
        # keeps hinting sane at high zoom.
        font: QFont = qt_font(prim.style.role, prim.style.size_pt)
        px_size = max(1.0, prim.style.size_pt * self._px_per_mm / 2.834645669291339)
        font.setPixelSize(int(round(px_size)))
        inv = 1.0 / self._px_per_mm
        p.scale(inv, inv)
        p.setFont(font)
        p.setPen(QPen(_colour(prim.style.fill)))

        metrics = p.fontMetrics()
        width = metrics.horizontalAdvance(prim.text)
        dx = 0.0
        if prim.anchor is Anchor.BASELINE_CENTRE:
            dx = -width / 2.0
        elif prim.anchor is Anchor.BASELINE_RIGHT:
            dx = -float(width)
        p.drawText(QPointF(dx, 0.0), prim.text)
        p.restore()

    def symbol(self, prim: SymbolPrim) -> None:
        matrix = prim.matrix
        if matrix.cols == 0 or matrix.rows == 0:
            return
        module_mm = prim.size_mm / matrix.cols
        module_px = module_mm * self._px_per_mm

        if module_px < RASTER_THRESHOLD_PX and self._image_cache is not None:
            image = self._image_cache.image_for(matrix)
            self._p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            self._p.drawImage(
                QRectF(prim.x, prim.y, prim.size_mm, prim.size_mm), image
            )
            return

        rects = (
            self._image_cache.rects(matrix) if self._image_cache is not None else to_rects(matrix)
        )
        brush = QBrush(QColor(0, 0, 0))
        self._p.setPen(Qt.PenStyle.NoPen)
        for col, row, w, h in rects:
            self._p.fillRect(
                QRectF(
                    prim.x + col * module_mm,
                    prim.y + row * module_mm,
                    w * module_mm,
                    h * module_mm,
                ),
                brush,
            )

    # -- internals ----------------------------------------------------------

    def _apply(self, style: Style) -> None:
        if style.stroke:
            pen = QPen(_colour(style.stroke))
            # Cosmetic below one device pixel, so hairlines stay visible at any
            # zoom instead of disappearing.
            width_px = style.line_width_mm * self._px_per_mm
            pen.setWidthF(style.line_width_mm if width_px >= 1.0 else 0.0)
            pen.setCapStyle(_CAPS.get(style.cap, Qt.PenCapStyle.FlatCap))
            if style.dash_mm:
                pen.setDashPattern([max(d / max(style.line_width_mm, 0.01), 1.0)
                                    for d in style.dash_mm])
            self._p.setPen(pen)
        else:
            self._p.setPen(Qt.PenStyle.NoPen)

        if style.fill:
            self._p.setBrush(QBrush(_colour(style.fill)))
        else:
            self._p.setBrush(Qt.BrushStyle.NoBrush)
