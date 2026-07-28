"""Zoomable, scrollable preview and the miniature overview strip.

Both are built on QGraphicsView so panning, scrolling and fit-to-width come for
free. The item paints a `DrawList` through `QtPainter`, which is the same draw
list the PDF exporter consumes.

The page is drawn white on dark chrome deliberately: the preview shows what the
printer will produce, not a dark-mode reinterpretation of it.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

from aops.core.drawlist import DrawList, render
from aops.render.qt.backend import QtPainter
from aops.render.qt.image_cache import QtImageCache
from aops.ui.theme.palette import CANVAS_BG, PAPER_WHITE

MIN_ZOOM = 0.05
MAX_ZOOM = 40.0


class DrawListItem(QGraphicsItem):
    """A QGraphicsItem that paints one `DrawList` in millimetre coordinates."""

    def __init__(self, image_cache: QtImageCache) -> None:
        super().__init__()
        self._draw_list = DrawList(10.0, 10.0, ())
        self._cache = image_cache
        self._paper = True

    def set_draw_list(self, draw_list: DrawList) -> None:
        self.prepareGeometryChange()
        self._draw_list = draw_list
        self.update()

    def set_paper(self, enabled: bool) -> None:
        self._paper = enabled
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(0.0, 0.0, self._draw_list.width_mm, self._draw_list.height_mm)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # type: ignore[no-untyped-def]
        rect = self.boundingRect()
        if self._paper:
            painter.fillRect(rect, QBrush(QColor(PAPER_WHITE)))

        # Device pixels per millimetre, needed so the backend can decide between
        # vector rectangles and a cached raster, and size fonts correctly.
        scale = painter.transform().m11() or 1.0
        render(self._draw_list, QtPainter(painter, scale, self._cache))


class PreviewView(QGraphicsView):
    """Zoomable preview canvas."""

    zoomChanged = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._cache = QtImageCache()
        self._item = DrawListItem(self._cache)
        self._scene.addItem(self._item)

        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setBackgroundBrush(QBrush(QColor(CANVAS_BG)))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._zoom = 1.0
        #: While True the view refits on every resize and content change. Set
        #: False the moment the user zooms manually, so their choice sticks.
        self._auto_fit = True
        self._last_width_mm = 0.0

    def set_draw_list(self, draw_list: DrawList) -> None:
        width_changed = abs(draw_list.width_mm - self._last_width_mm) > 1e-6
        self._last_width_mm = draw_list.width_mm
        self._item.set_draw_list(draw_list)
        self._scene.setSceneRect(self._item.boundingRect().adjusted(-10, -10, 10, 10))
        if self._auto_fit and width_changed:
            self.fit_width()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        # The first meaningful viewport size only arrives once the window is
        # shown, so fitting during construction leaves the page microscopic.
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit_width()

    def image_cache(self) -> QtImageCache:
        return self._cache

    # -- zoom ---------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Ctrl+wheel zooms; plain wheel scrolls, as in every CAD tool."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self._auto_fit = False  # the user's zoom choice now wins
            self.zoom_by(factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def zoom_by(self, factor: float) -> None:
        target = self._zoom * factor
        if not (MIN_ZOOM <= target <= MAX_ZOOM):
            return
        self._zoom = target
        self.scale(factor, factor)
        self.zoomChanged.emit(self._zoom)

    def set_zoom(self, zoom: float) -> None:
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self.resetTransform()
        self.scale(zoom, zoom)
        self._zoom = zoom
        self.zoomChanged.emit(zoom)

    def fit_width(self) -> None:
        self._auto_fit = True
        rect = self._item.boundingRect()
        if rect.width() <= 0:
            return
        available = max(self.viewport().width() - 24, 40)
        self.set_zoom(available / rect.width())

    def fit_page(self) -> None:
        self._auto_fit = True
        rect = self._item.boundingRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        sx = max(self.viewport().width() - 24, 40) / rect.width()
        sy = max(self.viewport().height() - 24, 40) / rect.height()
        self.set_zoom(min(sx, sy))

    def zoom_actual(self) -> None:
        """1:1 in millimetres against the physical screen, as far as Qt knows it."""
        self._auto_fit = False
        dpi = self.logicalDpiX() or 96
        self.set_zoom(dpi / 25.4)

    def scale_percent(self) -> float:
        """Current zoom as a percentage of true physical size."""
        dpi = self.logicalDpiX() or 96
        return self._zoom / (dpi / 25.4) * 100.0


class OverviewBar(QGraphicsView):
    """Fixed-height miniature of the whole strip, not to scale."""

    pageClicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._cache = QtImageCache()
        self._item = DrawListItem(self._cache)
        self._item.set_paper(False)
        self._scene.addItem(self._item)

        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setBackgroundBrush(QBrush(QColor("#1b1e22")))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(96)
        self.setInteractive(False)

    def set_draw_list(self, draw_list: DrawList) -> None:
        self._item.set_draw_list(draw_list)
        rect = self._item.boundingRect()
        self._scene.setSceneRect(rect)
        if rect.width() > 0:
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        rect = self._item.boundingRect()
        if rect.width() > 0:
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
