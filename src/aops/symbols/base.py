"""The common symbol-encoder interface.

Every encoder returns a `ModuleMatrix`, never a bitmap. That is what allows the
PDF backend to draw crisp vector rectangles at exact millimetre dimensions
instead of embedding a raster that a RIP would resample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from aops.core.enums import Symbology
from aops.core.matrix import ModuleMatrix


@dataclass(frozen=True, slots=True)
class EncoderCapabilities:
    """What an encoder can accept."""

    charset: str  # "numeric" | "alnum" | "ascii" | "binary"
    max_payload_len: int
    quiet_modules: int


@runtime_checkable
class SymbolEncoder(Protocol):
    """Encodes a payload string into a grid of modules."""

    symbology: Symbology
    display_name: str
    available: bool

    def capabilities(self) -> EncoderCapabilities: ...

    def encode(self, payload: str) -> ModuleMatrix: ...
