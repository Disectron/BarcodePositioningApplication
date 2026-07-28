"""Index-to-position mapping and the human-readable position formula.

The formula this module produces is not decoration - it is what a controls
engineer types into the PLC. If it disagrees with the strip by even a constant
offset, the machine drives to the wrong place. So the formula string is
generated from the same code path that generates the positions, and the
installation guide prints it verbatim.
"""

from __future__ import annotations

from aops.core.cell import CellSpec
from aops.core.config import PositionConfig
from aops.core.enums import Direction, PitchMode


def code_count(pos: PositionConfig) -> int:
    """Number of codes in the configured index range (0 if the range is empty)."""
    if pos.increment <= 0:
        return 0
    if pos.end_index < pos.start_index:
        return 0
    return (pos.end_index - pos.start_index) // pos.increment + 1


def code_indices(pos: PositionConfig) -> tuple[int, ...]:
    """All printed index values, in strip order."""
    return tuple(
        pos.start_index + n * pos.increment for n in range(code_count(pos))
    )


def ordinal_of(index: int, pos: PositionConfig) -> int:
    """Zero-based position of `index` within the printed sequence."""
    if pos.increment <= 0:
        return 0
    return (index - pos.start_index) // pos.increment


def cell_slots(pos: PositionConfig) -> int:
    """Number of pitch-long slots the strip occupies.

    Under PER_CELL every printed code takes one slot. Under PER_INDEX skipped
    indices still consume a (blank) slot, so the literal ``Index * Pitch``
    relationship survives.
    """
    count = code_count(pos)
    if count == 0:
        return 0
    if pos.pitch_mode is PitchMode.PER_CELL:
        return count
    return pos.end_index - pos.start_index + 1


def _direction_sign(pos: PositionConfig) -> int:
    return 1 if pos.direction is Direction.FORWARD else -1


def slot_of(index: int, pos: PositionConfig) -> int:
    """Which pitch slot along the strip this index occupies (0-based, strip order)."""
    if pos.pitch_mode is PitchMode.PER_CELL:
        return ordinal_of(index, pos)
    return index - pos.start_index


def position_mm(index: int, pos: PositionConfig, cell: CellSpec) -> float:
    """Absolute machine position encoded for `index`, in millimetres."""
    steps = slot_of(index, pos)
    return pos.origin_mm + _direction_sign(pos) * steps * cell.pitch_mm


def max_position_mm(pos: PositionConfig, cell: CellSpec) -> float:
    """Largest absolute position value across the printed range."""
    indices = code_indices(pos)
    if not indices:
        return 0.0
    return max(abs(position_mm(i, pos, cell)) for i in indices)


def strip_length_mm(pos: PositionConfig, cell: CellSpec) -> float:
    """Length of the coded portion of the strip (excluding lead/trail margins)."""
    return cell_slots(pos) * cell.pitch_mm


def distance_per_code_mm(cell: CellSpec, pos: PositionConfig) -> float:
    """Physical distance represented by one increment of the index."""
    if pos.pitch_mode is PitchMode.PER_CELL:
        return cell.pitch_mm
    return cell.pitch_mm * pos.increment


def position_formula(pos: PositionConfig, cell: CellSpec) -> str:
    """Render the exact position formula as a human-readable string.

    Examples::

        P [mm] = Index x 25.000
        P [mm] = (Index - 100) x 25.000 + 250.000
        P [mm] = ((Index - 0) / 2) x 25.000
        P [mm] = 10500.000 - Index x 25.000
    """
    pitch = f"{cell.pitch_mm:.3f}"
    start = pos.start_index
    origin = pos.origin_mm
    reverse = pos.direction is Direction.REVERSE

    # The index expression, before multiplication by pitch.
    if pos.pitch_mode is PitchMode.PER_CELL and pos.increment != 1:
        term = f"((Index - {start}) / {pos.increment})"
    elif start != 0:
        term = f"(Index - {start})"
    else:
        term = "Index"

    if reverse:
        # Fold the origin and the descending run into a single leading constant
        # so the engineer sees one subtraction rather than a double negative.
        span = (cell_slots(pos) - 1) * cell.pitch_mm if cell_slots(pos) else 0.0
        lead = origin + span
        return f"P [mm] = {lead:.3f} - {term} x {pitch}"

    expr = f"P [mm] = {term} x {pitch}"
    if origin:
        sign = "+" if origin > 0 else "-"
        expr += f" {sign} {abs(origin):.3f}"
    return expr
