"""Data Matrix ECC200 encoding via pylibdmtx, recovered as a module matrix.

pylibdmtx returns a rendered RGB bitmap, not a module grid. For print output we
need the grid: drawing vector rectangles at exact millimetre positions gives
infinitely sharp edges at any RIP resolution, whereas embedding the bitmap makes
module edges dependent on how the RIP happens to resample it.

Recovery works because libdmtx renders deterministically: a fixed pixel margin
around the symbol, and a fixed number of pixels per module. Crop to the dark
bounding box, derive the module pitch, and sample module centres.

Two details are load-bearing:

* The module pixel size is **derived, not hardcoded**. libdmtx currently uses 5
  px, but a point release changing that default would silently produce garbage
  matrices - and a strip of unreadable codes is exactly the failure that must
  never ship quietly. Deriving it costs six lines.
* The extracted matrix is verified by feeding it back through a real decoder
  (`verify_roundtrip`). This turns "the PDF is probably right" into evidence.
"""

from __future__ import annotations

import threading

from aops.core.enums import Symbology
from aops.core.errors import EncoderUnavailable, SymbolExtractionError
from aops.core.matrix import ModuleMatrix, matrix_from_rows
from aops.symbols.base import EncoderCapabilities
from aops.symbols.compat import install_distutils_shim

# The shim must run before pylibdmtx is imported anywhere in the process.
install_distutils_shim()

#: libdmtx is not documented as thread-safe. One export worker thread plus this
#: lock means we never find out the hard way.
_DMTX_LOCK = threading.Lock()

#: Legal square ECC200 symbol sizes, in modules per side (ISO/IEC 16022).
_LEGAL_SQUARE_SIZES: frozenset[int] = frozenset(
    {10, 12, 14, 16, 18, 20, 22, 24, 26, 32, 36, 40, 44, 48, 52, 64, 72, 80, 88, 96, 104, 120, 132, 144}
)

#: Legal rectangular ECC200 sizes as (rows, cols).
_LEGAL_RECT_SIZES: frozenset[tuple[int, int]] = frozenset(
    {(8, 18), (8, 32), (12, 26), (12, 36), (16, 36), (16, 48)}
)

#: Candidate pixels-per-module values, most likely first.
_MODULE_PX_CANDIDATES: tuple[int, ...] = (5, 4, 6, 3, 8, 10, 2)

_DARK_THRESHOLD = 128


def _import_pylibdmtx():  # type: ignore[no-untyped-def]
    try:
        from pylibdmtx import pylibdmtx as _dmtx
    except ImportError as exc:
        raise EncoderUnavailable(
            "pylibdmtx could not be imported. Install it with 'pip install pylibdmtx' "
            "and ensure the native library is present "
            "(Debian/Ubuntu: 'sudo apt-get install libdmtx-dev')."
        ) from exc
    except OSError as exc:
        raise EncoderUnavailable(
            "The native libdmtx shared library was not found. On Debian/Ubuntu install "
            "it with 'sudo apt-get install libdmtx-dev' (note that libdmtx0b has no "
            f"install candidate on recent releases). Underlying error: {exc}"
        ) from exc
    return _dmtx


def _to_gray(pixels: bytes, width: int, height: int, bpp: int) -> list[list[int]]:
    """Convert the encoder's packed pixel buffer to a grayscale grid.

    Done by hand rather than through Pillow so that the pure extraction logic has
    no image-library dependency and stays trivially testable.
    """
    stride = bpp // 8
    if stride < 1:
        raise SymbolExtractionError(f"Unsupported bit depth {bpp} from the Data Matrix encoder.")
    grid: list[list[int]] = []
    for y in range(height):
        row: list[int] = []
        base = y * width * stride
        for x in range(width):
            off = base + x * stride
            if stride >= 3:
                # Rec. 601 luma is overkill for a pure black/white render, but it
                # costs nothing and tolerates any anti-aliasing.
                value = (pixels[off] * 299 + pixels[off + 1] * 587 + pixels[off + 2] * 114) // 1000
            else:
                value = pixels[off]
            row.append(value)
        grid.append(row)
    return grid


def _dark_bbox(gray: list[list[int]]) -> tuple[int, int, int, int]:
    """Bounding box of dark pixels as (x0, y0, x1, y1), inclusive."""
    rows = [y for y, row in enumerate(gray) if any(v < _DARK_THRESHOLD for v in row)]
    if not rows:
        raise SymbolExtractionError("Encoder produced a blank bitmap - no dark modules found.")
    cols = [
        x
        for x in range(len(gray[0]))
        if any(gray[y][x] < _DARK_THRESHOLD for y in range(len(gray)))
    ]
    return cols[0], rows[0], cols[-1], rows[-1]


def _derive_module_px(side_px: int, other_px: int) -> int:
    """Work out how many pixels libdmtx used per module.

    Tries plausible values and accepts the first that divides both dimensions
    exactly *and* yields a legal ECC200 symbol size.
    """
    for candidate in _MODULE_PX_CANDIDATES:
        if side_px % candidate or other_px % candidate:
            continue
        n_cols = side_px // candidate
        n_rows = other_px // candidate
        if n_rows == n_cols and n_rows in _LEGAL_SQUARE_SIZES:
            return candidate
        if (n_rows, n_cols) in _LEGAL_RECT_SIZES:
            return candidate
    raise SymbolExtractionError(
        f"Could not determine the module pitch of a {side_px}x{other_px} px Data Matrix "
        f"bitmap. The pylibdmtx rendering defaults may have changed; extraction has been "
        f"stopped rather than emitting a possibly-corrupt symbol."
    )


def extract_matrix(pixels: bytes, width: int, height: int, bpp: int, payload: str) -> ModuleMatrix:
    """Recover the module grid from an encoder bitmap."""
    gray = _to_gray(pixels, width, height, bpp)
    x0, y0, x1, y1 = _dark_bbox(gray)
    span_x, span_y = x1 - x0 + 1, y1 - y0 + 1

    module_px = _derive_module_px(span_x, span_y)
    n_cols, n_rows = span_x // module_px, span_y // module_px

    half = module_px // 2
    rows: list[list[bool]] = []
    for r in range(n_rows):
        y = y0 + r * module_px + half
        rows.append(
            [gray[y][x0 + c * module_px + half] < _DARK_THRESHOLD for c in range(n_cols)]
        )

    return matrix_from_rows(
        rows,
        symbology=Symbology.DATA_MATRIX.value,
        payload=payload,
        quiet_modules=1,  # ISO/IEC 16022 mandates a 1-module quiet zone
    )


class DataMatrixEncoder:
    """Data Matrix ECC200 encoder."""

    symbology = Symbology.DATA_MATRIX
    display_name = Symbology.DATA_MATRIX.display_name

    def __init__(self) -> None:
        self._unavailable_reason: str | None = None
        try:
            self._dmtx = _import_pylibdmtx()
        except EncoderUnavailable as exc:
            self._dmtx = None
            self._unavailable_reason = str(exc)

    @property
    def available(self) -> bool:
        return self._dmtx is not None

    @property
    def unavailable_reason(self) -> str | None:
        return self._unavailable_reason

    def capabilities(self) -> EncoderCapabilities:
        return EncoderCapabilities(charset="ascii", max_payload_len=1556, quiet_modules=1)

    def encode(self, payload: str) -> ModuleMatrix:
        if self._dmtx is None:
            raise EncoderUnavailable(self._unavailable_reason or "libdmtx unavailable")
        with _DMTX_LOCK:
            encoded = self._dmtx.encode(payload.encode("ascii"))
        return extract_matrix(
            bytes(encoded.pixels), encoded.width, encoded.height, encoded.bpp, payload
        )

    def verify_roundtrip(self, matrix: ModuleMatrix) -> bool:
        """Re-render the extracted matrix and decode it, comparing payloads.

        At roughly 10-40 ms per symbol this is far too slow to run on every code
        of a long strip, and exactly right for a sample of them.
        """
        if self._dmtx is None:
            return False

        try:
            from PIL import Image
        except ImportError:  # pragma: no cover
            return False

        quiet, scale = 4, 8
        w = (matrix.cols + 2 * quiet) * scale
        h = (matrix.rows + 2 * quiet) * scale
        buf = bytearray(b"\xff" * (w * h))
        for r in range(matrix.rows):
            for c in range(matrix.cols):
                if not matrix.dark(r, c):
                    continue
                for dy in range(scale):
                    y = (r + quiet) * scale + dy
                    start = y * w + (c + quiet) * scale
                    buf[start : start + scale] = b"\x00" * scale

        image = Image.frombytes("L", (w, h), bytes(buf))
        with _DMTX_LOCK:
            results = self._dmtx.decode(image, max_count=1, timeout=2000)
        return bool(results) and results[0].data.decode("ascii", "replace") == matrix.payload
