"""The cell model and its invariants.

A *cell* is one pitch-long segment of the strip:

    |<---------------------- pitch 25.000 ---------------------->|
    |  margin_lr 7.500  |   symbol 10.000   |  margin_lr 7.500   |
                        |<qz>|         |<qz>|      qz = 1.000

The quiet zone is **carved out of the left/right margin, never added to the
cell**. That definition is the whole reason splice safety reduces to a single
inequality: if the symbol plus both its quiet zones fits inside the pitch, then
the white gap between adjacent symbols is at least two quiet zones wide, and a
cut at any cell boundary is automatically clear of ink.
"""

from __future__ import annotations

from dataclasses import dataclass

from aops.core.config import DimensionConfig
from aops.core.enums import LrMarginMode
from aops.core.errors import GeometryError
from aops.core.units import mm_to_um, um_to_mm

#: Minimum module size we consider printable/readable, in micrometres (0.30 mm).
#: Below this, 600 dpi printing can no longer render clean module edges and
#: most fixed-mount imagers struggle to resolve modules reliably.
MIN_MODULE_UM: int = 300

#: Module size above which the symbol is arguably wasting strip width.
GENEROUS_MODULE_UM: int = 1000


@dataclass(frozen=True, slots=True)
class CellSpec:
    """Fully resolved geometry of one cell, in integer micrometres."""

    pitch_um: int
    symbol_um: int
    margin_lr_um: int
    quiet_zone_um: int
    strip_height_um: int
    symbol_x_offset_um: int
    symbol_y_offset_um: int

    @property
    def pitch_mm(self) -> float:
        return um_to_mm(self.pitch_um)

    @property
    def symbol_mm(self) -> float:
        return um_to_mm(self.symbol_um)

    @property
    def margin_lr_mm(self) -> float:
        return um_to_mm(self.margin_lr_um)

    @property
    def quiet_zone_mm(self) -> float:
        return um_to_mm(self.quiet_zone_um)

    @property
    def strip_height_mm(self) -> float:
        return um_to_mm(self.strip_height_um)

    @property
    def white_gap_um(self) -> int:
        """White space between the ink of two adjacent symbols."""
        return self.pitch_um - self.symbol_um

    @property
    def splice_clearance_um(self) -> int:
        """Distance from a cell boundary to the nearest symbol ink.

        This is the safety margin a guillotine or trimmer has to play with. At
        the default 25/10 geometry it is 7.5 mm against a 1.0 mm requirement.
        """
        return self.margin_lr_um

    def module_um(self, matrix_cols: int) -> float:
        """Size of one symbol module in micrometres, for a given matrix width."""
        if matrix_cols <= 0:
            return 0.0
        return self.symbol_um / matrix_cols

    def module_mm(self, matrix_cols: int) -> float:
        return self.module_um(matrix_cols) / 1000.0


def resolve_cell(dim: DimensionConfig) -> CellSpec:
    """Build a `CellSpec` from authored dimensions.

    Resolves the over-determination between pitch, symbol size and margin
    according to `dim.lr_margin_mode`, then centres the symbol vertically in the
    strip band (plus any explicit offset).

    Raises `GeometryError` only for values that cannot produce a cell at all.
    Softer problems are reported by the validation layer so the user sees a
    message rather than an exception.
    """
    symbol_um = mm_to_um(dim.symbol_size_mm)
    quiet_um = mm_to_um(dim.quiet_zone_mm)
    height_um = mm_to_um(dim.strip_height_mm)

    if dim.lr_margin_mode is LrMarginMode.DRIVES_PITCH:
        margin_um = mm_to_um(dim.margin_lr_mm)
        pitch_um = symbol_um + 2 * margin_um
    else:
        pitch_um = mm_to_um(dim.pitch_mm)
        # Integer division: any odd micrometre goes to the right-hand margin via
        # the pitch, so cells still tile exactly at `n * pitch`.
        margin_um = (pitch_um - symbol_um) // 2

    if pitch_um <= 0:
        raise GeometryError(f"Cell pitch must be positive (got {um_to_mm(pitch_um):.3f} mm).")
    if symbol_um <= 0:
        raise GeometryError(f"Symbol size must be positive (got {um_to_mm(symbol_um):.3f} mm).")
    if height_um <= 0:
        raise GeometryError(f"Strip height must be positive (got {um_to_mm(height_um):.3f} mm).")

    v_offset_um = mm_to_um(dim.symbol_v_offset_mm)
    symbol_y_um = (height_um - symbol_um) // 2 + v_offset_um

    return CellSpec(
        pitch_um=pitch_um,
        symbol_um=symbol_um,
        margin_lr_um=margin_um,
        quiet_zone_um=quiet_um,
        strip_height_um=height_um,
        symbol_x_offset_um=margin_um,
        symbol_y_offset_um=symbol_y_um,
    )


def cell_invariants(cell: CellSpec) -> tuple[str, ...]:
    """Return the IDs of any violated cell invariants; empty means valid.

    Each ID corresponds 1:1 to a validation rule, so the rules layer can report
    them with user-facing text and a suggested fix.

    I3 is the master invariant - splice safety follows from it alone.
    """
    violations: list[str] = []

    if cell.pitch_um <= 0:
        violations.append("I1")
    if cell.symbol_um <= 0:
        violations.append("I2")
    if cell.symbol_um + 2 * cell.quiet_zone_um > cell.pitch_um:
        violations.append("I3")
    if cell.symbol_um + 2 * cell.quiet_zone_um > cell.strip_height_um:
        violations.append("I4")
    if cell.margin_lr_um < cell.quiet_zone_um:
        violations.append("I5")
    if cell.quiet_zone_um < 0:
        violations.append("I6")
    if cell.strip_height_um <= 0:
        violations.append("I7")

    return tuple(violations)
