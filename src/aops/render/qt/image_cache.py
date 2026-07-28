"""Raster tier of the symbol cache, owned by the Qt backend.

Lives here rather than in `symbols/` because a `QImage` must only be created on
the GUI thread, and because keeping Qt types out of the symbol layer is what
lets the core be tested with no Qt installed at all.

The cache key contains the matrix identity and nothing about geometry, so zoom
changes reuse everything.
"""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtGui import QImage

from aops.core.matrix import ModuleMatrix, to_rects


class QtImageCache:
    """Small LRU of rendered symbol images plus the shared rect decomposition."""

    def __init__(self, max_images: int = 64, max_rects: int = 8192) -> None:
        self._images: OrderedDict[tuple[str, str], QImage] = OrderedDict()
        self._rects: OrderedDict[tuple[str, str], tuple[tuple[int, int, int, int], ...]] = (
            OrderedDict()
        )
        self._max_images = max_images
        self._max_rects = max_rects

    def rects(self, matrix: ModuleMatrix) -> tuple[tuple[int, int, int, int], ...]:
        key = matrix.key
        cached = self._rects.get(key)
        if cached is not None:
            self._rects.move_to_end(key)
            return cached
        computed = to_rects(matrix)
        self._rects[key] = computed
        while len(self._rects) > self._max_rects:
            self._rects.popitem(last=False)
        return computed

    def image_for(self, matrix: ModuleMatrix) -> QImage:
        """One device pixel per module, scaled up by the painter when drawn."""
        key = matrix.key
        cached = self._images.get(key)
        if cached is not None:
            self._images.move_to_end(key)
            return cached

        image = QImage(matrix.cols, matrix.rows, QImage.Format.Format_Grayscale8)
        image.fill(0xFF)
        for r in range(matrix.rows):
            scan = image.scanLine(r)
            view = memoryview(scan).cast("B")
            for c in range(matrix.cols):
                if matrix.dark(r, c):
                    view[c] = 0x00

        self._images[key] = image
        while len(self._images) > self._max_images:
            self._images.popitem(last=False)
        return image

    def clear(self) -> None:
        self._images.clear()
        self._rects.clear()
