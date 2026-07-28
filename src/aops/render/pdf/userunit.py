"""`/UserUnit` support for ReportLab, which has none.

WHY THIS IS NEEDED
------------------
PDF 1.x caps a page at 14400 points (200 inches / 5080 mm). A 421-code strip at
25 mm pitch is 10.565 m = 29948 pt, which is 2.08x over. Emitting that size
directly produces a non-conformant page that Acrobat refuses or clamps.

PDF 1.6 added ``/UserUnit``: a multiplier on the page's coordinate system. Write
the MediaBox at 1/U of true size, declare ``/UserUnit U``, and the page still
measures true size while staying inside the conformant limit.

THE TRAP
--------
The obvious implementation - setting ``PDFPage.UserUnit`` as a class attribute -
silently does nothing. ``PDFPage.format()`` emits every key listed in
``__NoDefault__`` whose value is not None, but ``PDFCatalog.__init__`` pre-seeds
each of those keys to None *on the instance*, which shadows the class attribute.
The value therefore has to be set on the instance, at format time.

The patch is scoped to a context manager and fully reverted afterwards, so it
cannot leak into any other PDF this process writes.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager

from reportlab.pdfbase import pdfdoc

from aops.core.units import PDF_MAX_PT


def user_unit_for(width_pt: float, height_pt: float) -> float:
    """Smallest /UserUnit, rounded up to 2 dp, that fits the PDF page limit."""
    longest = max(width_pt, height_pt)
    if longest <= PDF_MAX_PT:
        return 1.0
    return math.ceil(longest / PDF_MAX_PT * 100.0) / 100.0


@contextmanager
def user_unit(value: float) -> Iterator[None]:
    """Emit ``/UserUnit value`` on every page written inside this block.

    A value of 1.0 or less is a no-op, so callers can wrap unconditionally.
    """
    if value <= 1.0:
        yield
        return

    original_nodefault = pdfdoc.PDFPage.__NoDefault__
    original_format = pdfdoc.PDFPage.format

    def format_with_user_unit(self, document):  # type: ignore[no-untyped-def]
        # Set on the instance: a class attribute is shadowed by the None that
        # PDFCatalog.__init__ writes for every __NoDefault__ key.
        self.UserUnit = value
        return original_format(self, document)

    pdfdoc.PDFPage.__NoDefault__ = list(original_nodefault) + ["UserUnit"]
    pdfdoc.PDFPage.format = format_with_user_unit
    try:
        yield
    finally:
        pdfdoc.PDFPage.__NoDefault__ = original_nodefault
        pdfdoc.PDFPage.format = original_format


def ensure_pdf_16(canvas) -> None:  # type: ignore[no-untyped-def]
    """Raise the declared PDF version to 1.6, required for /UserUnit.

    ReportLab's ``ensureMinPdfVersion`` takes named feature keys rather than a
    version tuple, so the version is set directly.
    """
    doc = canvas._doc
    current = getattr(doc, "_pdfVersion", (1, 3))
    if current < (1, 6):
        doc._pdfVersion = (1, 6)
