"""Symbol caching.

Three tiers, each with a different key and a different reason to exist:

L1 matrix
    ``(symbology, payload)`` -> `ModuleMatrix`. Encoding is the expensive step,
    so nothing is ever encoded twice - across the preview, the overview, and
    both exporters.
L2 rects
    matrix identity -> rectangle decomposition. Pure, and recomputed on every
    repaint and every PDF page if not cached.
L3 raster
    Owned by the Qt backend (see `render/qt/image_cache.py`), because a QImage
    must not be created off the GUI thread.

The critical property is that **the cache keys contain no geometry**. A matrix
for "010500" is scale-independent, so zooming the preview from 100 % to 400 %
re-uses every matrix and touches only the raster tier. That is what makes zoom
feel instant rather than re-encoding hundreds of symbols.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from aops.core.enums import Symbology
from aops.core.errors import SymbologyNotImplemented
from aops.core.matrix import ModuleMatrix, to_rects


@dataclass(frozen=True, slots=True)
class CacheStats:
    hits: int
    misses: int
    size: int
    max_size: int

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class SymbolCache:
    """Thread-safe LRU cache over the encoder registry."""

    def __init__(self, encoders: Mapping[Symbology, object], maxsize: int = 8192) -> None:
        self._encoders = encoders
        self._maxsize = maxsize
        self._matrices: OrderedDict[tuple[str, str], ModuleMatrix] = OrderedDict()
        self._rects: OrderedDict[tuple[str, str], tuple[tuple[int, int, int, int], ...]] = (
            OrderedDict()
        )
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def encoder_for(self, symbology: Symbology) -> object:
        encoder = self._encoders.get(symbology)
        if encoder is None:
            raise SymbologyNotImplemented(symbology.value, "No encoder is registered.")
        return encoder

    def get(self, symbology: Symbology, payload: str) -> ModuleMatrix:
        """Encode `payload`, or return the cached matrix."""
        key = (symbology.value, payload)
        with self._lock:
            cached = self._matrices.get(key)
            if cached is not None:
                self._matrices.move_to_end(key)
                self._hits += 1
                return cached
            self._misses += 1

        # Encode outside the lock: libdmtx has its own serialisation and holding
        # this lock across a native call would serialise the whole cache on it.
        encoder = self.encoder_for(symbology)
        matrix = encoder.encode(payload)  # type: ignore[attr-defined]

        with self._lock:
            self._matrices[key] = matrix
            self._matrices.move_to_end(key)
            while len(self._matrices) > self._maxsize:
                old, _ = self._matrices.popitem(last=False)
                self._rects.pop(old, None)
        return matrix

    def rects(self, matrix: ModuleMatrix) -> tuple[tuple[int, int, int, int], ...]:
        """Cached maximal-rectangle decomposition of a matrix."""
        key = matrix.key
        with self._lock:
            cached = self._rects.get(key)
            if cached is not None:
                self._rects.move_to_end(key)
                return cached
        computed = to_rects(matrix)
        with self._lock:
            self._rects[key] = computed
            self._rects.move_to_end(key)
            while len(self._rects) > self._maxsize:
                self._rects.popitem(last=False)
        return computed

    def prime(
        self,
        symbology: Symbology,
        payloads: Iterable[str],
        *,
        progress: Callable[[int, int], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        """Pre-encode a whole run so the drawing phase is pure cache hits.

        Progress is reported every 25 symbols rather than per symbol: at several
        thousand codes, emitting a cross-thread signal per item costs more than
        the encoding does.
        """
        items = list(payloads)
        total = len(items)
        for i, payload in enumerate(items, start=1):
            if cancel is not None and cancel.is_set():
                return
            self.get(symbology, payload)
            if progress is not None and (i % 25 == 0 or i == total):
                progress(i, total)

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                size=len(self._matrices),
                max_size=self._maxsize,
            )

    def clear(self) -> None:
        with self._lock:
            self._matrices.clear()
            self._rects.clear()
            self._hits = 0
            self._misses = 0


#: Narrowest matrix each symbology can produce - the probe's fallback when
#: encoding fails. Data Matrix starts at 10x10; QR has no version below 1,
#: which is 21x21. The old fallback was a bare 10 for everything, and a
#: solver working from it sized QR modules at half their real span.
FALLBACK_COLS: dict[Symbology, int] = {
    Symbology.DATA_MATRIX: 10,
    Symbology.QR: 21,
}


def probe_matrix_cols(
    cache: SymbolCache,
    symbology: Symbology,
    sample_payload: str,
    fallback: int | None = None,
) -> int:
    """Module count across for a representative payload.

    Needed early - the module size feeds validation, the scanner recommendation
    and the print-resolution check - but must never take down the UI when an
    encoder is unavailable, so failures fall back to the symbology's own
    minimum matrix rather than a Data Matrix-shaped constant.
    """
    try:
        return cache.get(symbology, sample_payload).cols
    except Exception:
        if fallback is not None:
            return fallback
        return FALLBACK_COLS.get(symbology, 10)
