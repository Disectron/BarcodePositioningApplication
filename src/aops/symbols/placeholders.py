"""Encoders for symbologies that are declared but not implemented.

These exist so that selecting Code 128, Code 39 or Aztec produces a clear,
specific refusal at three independent layers rather than a silent substitution:

1. The UI disables the combo entry and explains why in a tooltip.
2. Validation raises SYM-001 (FATAL), which blocks export.
3. `encode()` raises.

Substituting a different symbology would be the worst possible behaviour here.
A strip that looks right, scans, and reports the wrong thing is far more
dangerous than one that refuses to print.
"""

from __future__ import annotations

from dataclasses import dataclass

from aops.core.enums import Symbology
from aops.core.errors import SymbologyNotImplemented
from aops.core.matrix import ModuleMatrix
from aops.symbols.base import EncoderCapabilities

#: Why each reserved symbology is not implemented, shown in the UI tooltip.
PLACEHOLDER_REASONS: dict[Symbology, str] = {
    Symbology.CODE128: (
        "Code 128 is a linear symbology. It is supported by some positioning systems "
        "(Leuze BPS reads a 1-D barcode tape), but AOPS currently generates 2-D "
        "symbols only."
    ),
    Symbology.CODE39: (
        "Code 39 is a low-density linear symbology and is a poor fit for fine-pitch "
        "positioning. Reserved for a future release."
    ),
    Symbology.AZTEC: (
        "Aztec needs no quiet zone, which is attractive for dense strips, but it is "
        "not yet implemented. Reserved for a future release."
    ),
}


@dataclass(frozen=True, slots=True)
class UnavailableEncoder:
    """An encoder that always refuses, loudly."""

    symbology: Symbology
    reason: str
    available: bool = False

    @property
    def display_name(self) -> str:
        return self.symbology.display_name

    def capabilities(self) -> EncoderCapabilities:
        return EncoderCapabilities(charset="ascii", max_payload_len=0, quiet_modules=0)

    def encode(self, payload: str) -> ModuleMatrix:
        raise SymbologyNotImplemented(self.symbology.display_name, self.reason)
