"""Engineering ruler tick generation.

Ticks are generated in **absolute strip coordinates**, not page-relative ones,
so a ruler continues seamlessly across a page boundary: no duplicated tick at
the seam, no gap, and the labels keep counting up in real machine distance.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from math import ceil

from aops.core.units import mm_to_um, um_to_mm


class TickClass(IntEnum):
    """Tick emphasis levels, ordered so `max()` picks the strongest."""

    MINOR = 0  # 5 mm
    MEDIUM = 1  # 25 mm
    MAJOR = 2  # 50 mm
    EMPHASIS = 3  # 100 mm


@dataclass(frozen=True, slots=True)
class RulerSpec:
    """Tick intervals and their drawn lengths."""

    minor_mm: float = 5.0
    medium_mm: float = 25.0
    major_mm: float = 50.0
    emphasis_mm: float = 100.0
    minor_len_mm: float = 1.5
    medium_len_mm: float = 2.5
    major_len_mm: float = 3.5
    emphasis_len_mm: float = 5.0
    #: Label from 50 mm upward. Labelling only the 100 mm emphasis leaves a
    #: 277 mm sheet with just two or three numbers, which is not enough to
    #: position a tile against a steel tape.
    label_from: TickClass = TickClass.MAJOR

    def length_for(self, cls: TickClass) -> float:
        return {
            TickClass.MINOR: self.minor_len_mm,
            TickClass.MEDIUM: self.medium_len_mm,
            TickClass.MAJOR: self.major_len_mm,
            TickClass.EMPHASIS: self.emphasis_len_mm,
        }[cls]


@dataclass(frozen=True, slots=True)
class Tick:
    """One ruler tick at an absolute strip position."""

    x_um: int
    cls: TickClass
    label: str | None

    @property
    def x_mm(self) -> float:
        return um_to_mm(self.x_um)


def _classify(x_um: int, spec: RulerSpec) -> TickClass | None:
    """Strongest tick class that divides this position exactly."""
    for interval_mm, cls in (
        (spec.emphasis_mm, TickClass.EMPHASIS),
        (spec.major_mm, TickClass.MAJOR),
        (spec.medium_mm, TickClass.MEDIUM),
        (spec.minor_mm, TickClass.MINOR),
    ):
        step = mm_to_um(interval_mm)
        if step > 0 and x_um % step == 0:
            return cls
    return None


def ticks_between(
    x0_um: int,
    x1_um: int,
    spec: RulerSpec | None = None,
    *,
    origin_um: int = 0,
    label_scale: float = 1.0,
) -> tuple[Tick, ...]:
    """Generate ticks for the half-open absolute range ``[x0_um, x1_um)``.

    `origin_um` shifts the labelled distance so a strip whose machine datum is
    not at zero still reads correctly. `label_scale` is reserved for the
    miniature overview, which labels in metres rather than millimetres.
    """
    spec = spec or RulerSpec()
    step_um = mm_to_um(spec.minor_mm)
    if step_um <= 0 or x1_um <= x0_um:
        return ()

    first = ceil(x0_um / step_um) * step_um
    out: list[Tick] = []
    x = first
    while x < x1_um:
        cls = _classify(x, spec)
        if cls is not None:
            label = None
            if cls >= spec.label_from:
                value_mm = um_to_mm(x + origin_um) * label_scale
                label = f"{value_mm:.0f}"
            out.append(Tick(x_um=x, cls=cls, label=label))
        x += step_um
    return tuple(out)
