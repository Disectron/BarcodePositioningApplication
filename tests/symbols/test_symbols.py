"""Symbol encoding, matrix recovery and decode round-trip.

The round-trip test is the evidence that vector output is safe: the module
matrix extracted from the encoder bitmap is re-rendered and fed back through a
real Data Matrix decoder. If that passes, the rectangles drawn into the PDF
describe a readable symbol.
"""

from __future__ import annotations

import pytest

from aops.core.enums import Symbology
from aops.core.errors import SymbologyNotImplemented
from aops.core.matrix import matrix_from_rows, to_rects
from aops.symbols.cache import SymbolCache
from aops.symbols.compat import install_distutils_shim
from aops.symbols.datamatrix import DataMatrixEncoder
from aops.symbols.placeholders import UnavailableEncoder
from aops.symbols.qr import QrEncoder
from aops.symbols.registry import build_registry


@pytest.fixture(scope="module")
def dm() -> DataMatrixEncoder:
    encoder = DataMatrixEncoder()
    if not encoder.available:
        pytest.skip(f"libdmtx unavailable: {encoder.unavailable_reason}")
    return encoder


# -- compatibility shim -----------------------------------------------------


def test_shim_is_idempotent():
    install_distutils_shim()
    install_distutils_shim()
    from distutils.version import LooseVersion  # noqa: PLC0415

    assert LooseVersion("0.7.7") >= LooseVersion("0.7.4")
    assert LooseVersion("0.7.4") < LooseVersion("0.7.7")


# -- Data Matrix ------------------------------------------------------------


@pytest.mark.parametrize("payload", ["000000", "000025", "010500", "999999", "0010500"])
def test_datamatrix_roundtrip(dm: DataMatrixEncoder, payload: str):
    """The extracted matrix must decode back to the original payload."""
    matrix = dm.encode(payload)
    assert matrix.payload == payload
    assert matrix.rows == matrix.cols
    assert dm.verify_roundtrip(matrix), f"{payload} failed decode verification"


def test_matrix_size_constant_for_fixed_digits(dm: DataMatrixEncoder):
    """A mid-strip matrix size change would alter module size mid-strip."""
    sizes = {dm.encode(f"{i * 25:06d}").cols for i in range(0, 421, 37)}
    assert len(sizes) == 1, f"matrix size varies across the strip: {sizes}"


def test_six_digit_mm_payload_still_fits_ten_modules(dm: DataMatrixEncoder):
    """Encoding absolute millimetres costs nothing versus a 4-digit index."""
    assert dm.encode("0000").cols == 10
    assert dm.encode("999999").cols == 10


def test_corrupt_bitmap_is_rejected_not_guessed(dm: DataMatrixEncoder):
    from aops.core.errors import SymbolExtractionError
    from aops.symbols.datamatrix import extract_matrix

    # A bitmap whose dark extent is not a whole number of plausible modules.
    width = height = 37
    pixels = bytes([0] * (width * height * 3))
    with pytest.raises(SymbolExtractionError):
        extract_matrix(pixels, width, height, 24, "x")


# -- QR ---------------------------------------------------------------------


def test_qr_matrix_shape():
    encoder = QrEncoder()
    if not encoder.available:
        pytest.skip("qrcode unavailable")
    matrix = encoder.encode("010500")
    # QR version v has 21 + 4(v-1) modules per side.
    assert (matrix.cols - 21) % 4 == 0
    assert matrix.quiet_modules == 4


def test_datamatrix_is_coarser_than_qr(dm: DataMatrixEncoder):
    """Why industrial position tape uses Data Matrix."""
    qr = QrEncoder()
    if not qr.available:
        pytest.skip("qrcode unavailable")
    assert dm.encode("010500").cols < qr.encode("010500").cols


# -- placeholders -----------------------------------------------------------


@pytest.mark.parametrize("symbology", [Symbology.CODE128, Symbology.CODE39, Symbology.AZTEC])
def test_placeholders_raise_and_never_substitute(symbology: Symbology):
    encoder = build_registry()[symbology]
    assert isinstance(encoder, UnavailableEncoder)
    assert not encoder.available
    with pytest.raises(SymbologyNotImplemented):
        encoder.encode("000000")


# -- rectangle decomposition ------------------------------------------------


def test_to_rects_covers_exactly_the_dark_modules():
    rows = [
        [True, True, False, True],
        [True, True, False, True],
        [False, False, False, True],
    ]
    matrix = matrix_from_rows(rows, symbology="test", payload="x", quiet_modules=0)
    covered: set[tuple[int, int]] = set()
    for col, row, w, h in to_rects(matrix):
        for dy in range(h):
            for dx in range(w):
                cell = (row + dy, col + dx)
                assert cell not in covered, "rectangles overlap"
                covered.add(cell)
    expected = {(r, c) for r in range(3) for c in range(4) if rows[r][c]}
    assert covered == expected


def test_to_rects_reduces_draw_count(dm: DataMatrixEncoder):
    matrix = dm.encode("010500")
    assert len(to_rects(matrix)) < matrix.dark_count


# -- cache ------------------------------------------------------------------


def test_cache_avoids_repeat_encoding(dm: DataMatrixEncoder):
    cache = SymbolCache(build_registry())
    payloads = [f"{i * 25:06d}" for i in range(50)]
    cache.prime(Symbology.DATA_MATRIX, payloads)
    misses = cache.stats().misses
    cache.prime(Symbology.DATA_MATRIX, payloads)
    assert cache.stats().misses == misses, "second pass should be entirely cached"
    assert cache.stats().hits >= len(payloads)


def test_cache_key_excludes_geometry(dm: DataMatrixEncoder):
    """Zooming must not invalidate the matrix cache."""
    cache = SymbolCache(build_registry())
    first = cache.get(Symbology.DATA_MATRIX, "010500")
    second = cache.get(Symbology.DATA_MATRIX, "010500")
    assert first is second


# -- the probe's fallback ---------------------------------------------------


def test_probe_falls_back_to_the_symbologys_own_minimum():
    """An empty registry cannot encode anything, so the probe answers from
    knowledge instead: the smallest matrix the symbology can produce. The old
    fallback was a bare 10 for everything - Data Matrix's minimum - and a
    solver working from it sized QR modules at half their real span.
    """
    from aops.symbols.cache import probe_matrix_cols

    empty = SymbolCache({})
    assert probe_matrix_cols(empty, Symbology.DATA_MATRIX, "0000") == 10
    assert probe_matrix_cols(empty, Symbology.QR, "0000") == 21
    # An explicit fallback still wins, for callers that know better.
    assert probe_matrix_cols(empty, Symbology.QR, "0000", fallback=7) == 7
