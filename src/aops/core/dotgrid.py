"""How a symbol lands on the printer's dot grid.

A thermal printer can only put ink on whole dots. If one symbol module is not a
whole number of dots wide, the rasteriser has to round every module boundary to
the nearest dot, and the modules come out alternating between two different
widths.

    Symbol 10.000 mm, Data Matrix 10 modules across, 300 dpi
      one dot   = 25.4 / 300         = 0.0847 mm
      one module = 10.000 / 10       = 1.0000 mm = 11.811 dots

    Module boundaries land at 11.811, 23.622, 35.433 ... dots, which round to
    12, 24, 35 ... so the printed modules are 12, 12, 11, 12, 12, 11 ... dots.

Two numbers come out of that:

* **Module-width variation.** Widths differ by exactly one dot whenever the
  module is not a whole number of dots, which at 11.811 dots is 8.5% of a
  module. That is a real spread in ink coverage between neighbouring modules.
* **Grid deviation.** Each boundary sits up to half a dot from where the ideal
  grid puts it - 0.042 mm at 300 dpi. ISO/IEC 15415 measures exactly this as
  grid non-uniformity.

Both go to zero if the symbol size is chosen so a module is a whole number of
dots. For the case above that is 12 dots, i.e. a 10.160 mm symbol - a 1.6%
size change that buys an exactly uniform symbol.

HOW MUCH THIS ACTUALLY MATTERS, HONESTLY
----------------------------------------
It scales with how few dots there are, and at a comfortable module size it is a
small effect. Half a dot expressed in modules:

      dots/module     grid deviation      1-dot width variation
        23.6            0.021 module            4.2%
        11.8            0.042 module            8.5%
         8.0            0.063 module            0.0%  (on grid)
         4.0            0.125 module           25.0%

ISO/IEC 15415 grades grid non-uniformity A at 0.38 module or better, so at ten
or twenty dots per module the rounding is nowhere near the dominant defect - it
is worth fixing because it is free, not because the symbol would fail. It turns
serious only where the module is a handful of dots wide, which is the same place
PRN-005 and PRN-006 are already objecting on other grounds.

So the severity attached to this is graded by the variation rather than flat.
Reporting "your codes are misprinted" for a 4% effect would spend credibility
that the low-dot case actually needs.

WHY THIS IS NOT JUST "PRINT AT HIGHER RESOLUTION"
-------------------------------------------------
It does not improve with resolution, it only gets finer. 1 mm modules are
11.811 dots at 300 dpi and 23.622 at 600 - still fractional, still alternating,
just by a smaller absolute amount. The fix is to land on the grid, at whatever
resolution the printer runs.

The direction of the snap is not free. Growing the symbol can break the splice
guarantee (symbol + two quiet zones must fit inside the pitch), so a snap that
would do that goes down to the next whole dot instead of up, and one that cannot
go anywhere legal reports that rather than suggesting an illegal geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, isclose

from aops.core.units import mm_per_dot

#: A module within this fraction of a dot of whole is treated as on-grid.
#: Not exact equality: 203 dpi puts a 1.000 mm module at 7.992 dots, which is
#: 8 dots for every purpose that matters - the remaining eight thousandths of a
#: dot is 0.0001 mm of ink and no rasteriser resolves it.
ON_GRID_TOLERANCE_DOTS: float = 0.02

#: Module-width variation above which the mismatch is worth a warning rather
#: than a note. Ten percent is one dot in ten, i.e. fewer than ten dots across a
#: module - below that the printer is coarse enough relative to the code that a
#: single dot of rounding is a visible fraction of it.
NOTABLE_VARIATION_PERCENT: float = 10.0


@dataclass(frozen=True, slots=True)
class DotFit:
    """Where a requested symbol size sits relative to the dot grid.

    `snapped_symbol_mm` is 0.0 when no whole-dot size is legal, which is the
    caller's signal to report the problem rather than offer a correction.
    """

    dpi: int
    matrix_cols: int
    requested_symbol_mm: float
    #: Exact, fractional dots across one module at the requested size.
    module_dots: float
    #: Whole dots per module of the recommended size, or 0 if none is legal.
    snapped_dots: int
    #: The recommended symbol size, or 0.0 if none is legal.
    snapped_symbol_mm: float
    #: True when the snap had to go down because going up broke a constraint.
    snapped_down: bool

    @property
    def dot_size_mm(self) -> float:
        return mm_per_dot(self.dpi) if self.dpi > 0 else 0.0

    @property
    def is_on_grid(self) -> bool:
        """True when modules are already a whole number of dots."""
        if self.module_dots <= 0.0:
            return False
        nearest = round(self.module_dots)
        return nearest >= 1 and abs(self.module_dots - nearest) <= ON_GRID_TOLERANCE_DOTS

    @property
    def has_fix(self) -> bool:
        """True when there is a worthwhile correction to offer.

        Gated on being off-grid, not merely on the numbers differing. At 203 dpi
        a 1.000 mm module is 7.992 dots and the exact whole-dot size is 10.010
        mm; nudging the user from 10.000 to 10.010 would be noise dressed up as
        a defect.
        """
        return (
            not self.is_on_grid
            and self.snapped_symbol_mm > 0.0
            and not isclose(self.snapped_symbol_mm, self.requested_symbol_mm, abs_tol=5e-4)
        )

    @property
    def module_variation_percent(self) -> float:
        """Spread between the widest and narrowest printed module.

        One dot, as a percentage of the nominal module, since a fractional
        module always rasterises to either floor or ceil of its dot count.
        """
        if self.is_on_grid or self.module_dots <= 0.0:
            return 0.0
        return 100.0 / self.module_dots

    @property
    def grid_deviation_mm(self) -> float:
        """Worst-case distance from a printed module edge to the ideal grid."""
        return 0.0 if self.is_on_grid else self.dot_size_mm / 2.0

    @property
    def is_notable(self) -> bool:
        """True when the mismatch is large enough to be worth more than a note."""
        return self.module_variation_percent > NOTABLE_VARIATION_PERCENT

    @property
    def size_change_mm(self) -> float:
        """How much the symbol moves if the snap is taken. Signed."""
        if self.snapped_symbol_mm <= 0.0:
            return 0.0
        return self.snapped_symbol_mm - self.requested_symbol_mm


def dots_per_module(symbol_mm: float, matrix_cols: int, dpi: int) -> float:
    """Printer dots across one symbol module. Fractional by nature."""
    if matrix_cols <= 0 or dpi <= 0 or symbol_mm <= 0.0:
        return 0.0
    return (symbol_mm / matrix_cols) / mm_per_dot(dpi)


def symbol_mm_for_dots(dots: int, matrix_cols: int, dpi: int) -> float:
    """Symbol size whose modules are exactly `dots` printer dots wide."""
    if dots <= 0 or matrix_cols <= 0 or dpi <= 0:
        return 0.0
    return dots * mm_per_dot(dpi) * matrix_cols


def fit_to_dot_grid(
    symbol_mm: float,
    matrix_cols: int,
    dpi: int,
    *,
    max_symbol_mm: float = 0.0,
    min_module_mm: float = 0.0,
) -> DotFit:
    """Find the nearest symbol size whose modules are a whole number of dots.

    `max_symbol_mm` is the ceiling the rest of the geometry imposes - normally
    pitch minus two quiet zones, the splice guarantee. Pass 0.0 for no ceiling.

    Rounding is to the nearest whole dot, except that a size over the ceiling is
    never suggested: it would trade a printing defect for a strip that cannot be
    cut safely, which is a much worse trade. In that case the snap goes *down*
    one dot instead, and if even that is illegal there is no suggestion to make.
    """
    exact = dots_per_module(symbol_mm, matrix_cols, dpi)
    if exact <= 0.0:
        return DotFit(dpi, matrix_cols, symbol_mm, 0.0, 0, 0.0, False)

    def legal(dots: int) -> bool:
        if dots < 1:
            return False
        candidate = symbol_mm_for_dots(dots, matrix_cols, dpi)
        too_big = max_symbol_mm > 0.0 and candidate > max_symbol_mm + 5e-4
        too_fine = (
            min_module_mm > 0.0 and candidate / matrix_cols < min_module_mm - 5e-7
        )
        return not (too_big or too_fine)

    # Nearest first, then the other side, then progressively smaller. Growing
    # past the ceiling is never explored: the constraint is one-sided, so once
    # the nearest candidate is too big, only downward candidates can be legal.
    nearest = round(exact)
    candidates = [nearest, floor(exact), ceil(exact)]
    candidates += list(range(min(candidates) - 1, 0, -1))

    for dots in candidates:
        if legal(dots):
            return DotFit(
                dpi=dpi,
                matrix_cols=matrix_cols,
                requested_symbol_mm=symbol_mm,
                module_dots=exact,
                snapped_dots=dots,
                snapped_symbol_mm=symbol_mm_for_dots(dots, matrix_cols, dpi),
                snapped_down=dots < nearest,
            )

    return DotFit(dpi, matrix_cols, symbol_mm, exact, 0, 0.0, False)
