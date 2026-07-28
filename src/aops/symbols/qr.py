"""QR Code encoding.

Simpler than Data Matrix because the `qrcode` library exposes the module grid
directly via ``get_matrix()``; no bitmap round trip is needed.

Worth knowing when choosing between the two: for the short numeric payloads a
positioning strip uses, Data Matrix is dramatically more efficient. A six-digit
payload fits a 10x10 Data Matrix but needs a 21x21 QR - so at a fixed 10 mm
symbol the module size is 1.000 mm versus 0.476 mm. Coarser modules print more
cleanly and read from further away, which is why industrial positioning tape is
Data Matrix in practice.
"""

from __future__ import annotations

from aops.core.enums import QrEcc, Symbology
from aops.core.errors import EncoderUnavailable
from aops.core.matrix import ModuleMatrix, matrix_from_rows
from aops.symbols.base import EncoderCapabilities

_ECC_MAP = {"L": 1, "M": 0, "Q": 3, "H": 2}  # qrcode.constants values


class QrEncoder:
    """QR Code encoder."""

    symbology = Symbology.QR
    display_name = Symbology.QR.display_name

    def __init__(self, ecc: QrEcc = QrEcc.M, version: int = 0) -> None:
        self.ecc = ecc
        self.version = version
        self._unavailable_reason: str | None = None
        try:
            import qrcode  # noqa: F401

            self._ok = True
        except ImportError as exc:
            self._ok = False
            self._unavailable_reason = (
                f"The 'qrcode' package could not be imported: {exc}. "
                f"Install it with 'pip install qrcode'."
            )

    @property
    def available(self) -> bool:
        return self._ok

    @property
    def unavailable_reason(self) -> str | None:
        return self._unavailable_reason

    def capabilities(self) -> EncoderCapabilities:
        return EncoderCapabilities(charset="ascii", max_payload_len=4296, quiet_modules=4)

    def encode(self, payload: str) -> ModuleMatrix:
        if not self._ok:
            raise EncoderUnavailable(self._unavailable_reason or "qrcode unavailable")
        import qrcode

        qr = qrcode.QRCode(
            version=self.version or None,
            error_correction=_ECC_MAP[self.ecc.value],
            box_size=1,
            border=0,  # bare modules; the quiet zone is applied by the layout layer
        )
        qr.add_data(payload)
        qr.make(fit=self.version == 0)
        return matrix_from_rows(
            [list(row) for row in qr.get_matrix()],
            symbology=Symbology.QR.value,
            payload=payload,
            quiet_modules=4,  # ISO/IEC 18004 mandates 4 modules
        )
