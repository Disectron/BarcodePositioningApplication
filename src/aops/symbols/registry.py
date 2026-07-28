"""Encoder registry.

Built by a function and injected, never a module-level singleton - the codebase
has no global mutable state, and a test needs to be able to construct a registry
with a deliberately-broken encoder.

Adding a new symbology is one encoder module plus one line here.
"""

from __future__ import annotations

from collections.abc import Mapping

from aops.core.config import SymbolConfig
from aops.core.enums import Symbology
from aops.symbols.datamatrix import DataMatrixEncoder
from aops.symbols.placeholders import PLACEHOLDER_REASONS, UnavailableEncoder
from aops.symbols.qr import QrEncoder


def build_registry(symbol_cfg: SymbolConfig | None = None) -> Mapping[Symbology, object]:
    """Construct the full symbology map.

    QR is parameterised by the current configuration (error-correction level and
    version), so the registry is rebuilt when those change. Data Matrix needs no
    parameters, and unimplemented symbologies get an encoder that refuses.
    """
    cfg = symbol_cfg or SymbolConfig()
    registry: dict[Symbology, object] = {
        Symbology.DATA_MATRIX: DataMatrixEncoder(),
        Symbology.QR: QrEncoder(ecc=cfg.qr_ecc, version=cfg.qr_version),
    }
    for symbology, reason in PLACEHOLDER_REASONS.items():
        registry[symbology] = UnavailableEncoder(symbology=symbology, reason=reason)
    return registry
