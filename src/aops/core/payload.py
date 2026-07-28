"""Building the string that each symbol encodes.

The strip encodes **absolute position in millimetres**, not an index. That makes
the strip self-describing: a scanner reads a real machine coordinate and the PLC
does no arithmetic. Measurements confirm this costs nothing - a six-digit
millimetre payload (up to 999 m) still fits the same 10x10 Data Matrix as a
four-digit index; only at seven digits does the matrix grow to 12x12.

Because the human-readable text renders this same payload, what an engineer
reads on the strip is exactly what the scanner decodes. There is no second
numbering that can drift out of sync.
"""

from __future__ import annotations

from dataclasses import dataclass

from aops.core.cell import CellSpec
from aops.core.config import PayloadConfig, PositionConfig
from aops.core.enums import PayloadSource
from aops.core.positions import code_indices, position_mm


@dataclass(frozen=True, slots=True)
class PayloadIssue:
    """A problem detected while building payloads."""

    code: str
    detail: str


def payload_value(index: int, pos: PositionConfig, cell: CellSpec, pay: PayloadConfig) -> int:
    """Integer value encoded for `index`, already scaled by `unit_scale`."""
    if pay.source is PayloadSource.INDEX:
        return index
    return round(position_mm(index, pos, cell) * pay.unit_scale)


def format_payload(value: int, pay: PayloadConfig) -> str:
    """Zero-pad and decorate an integer payload value."""
    if value < 0:
        # A leading minus would break the fixed-width contract the PLC relies on,
        # so negatives are encoded with an explicit sign inside the padding.
        body = f"-{abs(value):0{max(pay.digits - 1, 1)}d}"
    else:
        body = f"{value:0{pay.digits}d}"
    return f"{pay.prefix}{body}{pay.suffix}"


def payload_for(index: int, pos: PositionConfig, cell: CellSpec, pay: PayloadConfig) -> str:
    """The complete string encoded into the symbol at `index`."""
    return format_payload(payload_value(index, pos, cell, pay), pay)


def all_payloads(
    pos: PositionConfig, cell: CellSpec, pay: PayloadConfig
) -> tuple[str, ...]:
    """Payloads for every printed index, in strip order."""
    return tuple(payload_for(i, pos, cell, pay) for i in code_indices(pos))


def required_digits(pos: PositionConfig, cell: CellSpec, pay: PayloadConfig) -> int:
    """Minimum `digits` that can represent every payload without truncation."""
    indices = code_indices(pos)
    if not indices:
        return 1
    widest = max(abs(payload_value(i, pos, cell, pay)) for i in indices)
    return max(1, len(str(widest)))


def precision_loss_mm(pos: PositionConfig, cell: CellSpec, pay: PayloadConfig) -> float:
    """Largest rounding error introduced by the chosen `unit_scale`, in mm.

    A 12.5 mm pitch with ``unit_scale = 1`` cannot represent 37.5 mm, so every
    other code would be half a millimetre out. Reporting this lets the engineer
    choose tenths of a millimetre instead of discovering the drift on the machine.
    """
    worst = 0.0
    for index in code_indices(pos):
        exact = position_mm(index, pos, cell) * pay.unit_scale
        error = abs(exact - round(exact)) / pay.unit_scale
        worst = max(worst, error)
    return worst
