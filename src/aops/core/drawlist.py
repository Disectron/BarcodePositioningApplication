"""The backend-agnostic display list.

Layout is written exactly **once**, here and in `core.layout`, with no Qt and no
ReportLab anywhere near it. Both backends then walk the same list. That is what
guarantees the on-screen preview and the exported PDF cannot disagree: there is
no second layout implementation to drift.

Coordinates are in **design millimetres, Y down, origin at the top left**. Y-down
matches Qt's convention directly; the PDF backend flips once in its transform.

`SymbolPrim` deliberately carries the `ModuleMatrix` rather than pre-expanded
rectangles, so each backend can choose its own strategy: the PDF backend always
emits vector rectangles, while the Qt backend blits a cached image once modules
fall below a few pixels. Same layout, different execution.

Adding a new output format (SVG, PNG, DXF) means implementing `Painter` and
nothing else - the layout code is untouched.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, TypeAlias

from aops.core.enums import Anchor, FontRole, LineCap
from aops.core.matrix import ModuleMatrix

#: An RGB colour with components in 0.0-1.0.
RGB: TypeAlias = tuple[float, float, float]

BLACK: RGB = (0.0, 0.0, 0.0)
WHITE: RGB = (1.0, 1.0, 1.0)
MID_GREY: RGB = (0.45, 0.45, 0.45)
LIGHT_GREY: RGB = (0.75, 0.75, 0.75)


@dataclass(frozen=True, slots=True)
class Style:
    """Stroke and fill for a geometric primitive."""

    stroke: RGB | None = BLACK
    fill: RGB | None = None
    line_width_mm: float = 0.2
    dash_mm: tuple[float, ...] = ()
    cap: LineCap = LineCap.BUTT


@dataclass(frozen=True, slots=True)
class TextStyle:
    """Font role, size and colour for a text primitive."""

    role: FontRole = FontRole.MONO
    size_pt: float = 7.0
    fill: RGB = BLACK


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    w: float
    h: float
    style: Style = field(default_factory=Style)


@dataclass(frozen=True, slots=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    style: Style = field(default_factory=Style)


@dataclass(frozen=True, slots=True)
class PolyLine:
    pts: tuple[tuple[float, float], ...]
    style: Style = field(default_factory=Style)
    close: bool = False


@dataclass(frozen=True, slots=True)
class Text:
    x: float
    y: float
    text: str
    style: TextStyle = field(default_factory=TextStyle)
    anchor: Anchor = Anchor.BASELINE_LEFT
    rotation_deg: float = 0.0


@dataclass(frozen=True, slots=True)
class SymbolPrim:
    """A symbol to be drawn at `size_mm` square, top-left at (x, y)."""

    x: float
    y: float
    size_mm: float
    matrix: ModuleMatrix


Primitive: TypeAlias = Rect | Line | PolyLine | Text | SymbolPrim


@dataclass(frozen=True, slots=True)
class DrawList:
    """A page (or page region) of primitives with its own extent."""

    width_mm: float
    height_mm: float
    items: tuple[Primitive, ...] = ()

    def extend(self, more: Sequence[Primitive]) -> DrawList:
        return DrawList(self.width_mm, self.height_mm, self.items + tuple(more))


@dataclass(frozen=True, slots=True)
class PageDrawLists:
    """The two coordinate spaces of one printed sheet.

    This split is not cosmetic. Registration marks exist to align *sheets*, so
    they must sit at fixed physical positions and must NOT be scaled by the
    printer-compensation factor. Cut marks indicate where the *content* is to be
    trimmed, so they must scale with it. Keeping the two in separate draw lists
    makes that correct by construction rather than by remembering.
    """

    sheet: DrawList  # physical sheet space; printer scaling NOT applied
    content: DrawList  # design space inside the margins; scaling applied at emit


class Painter(Protocol):
    """What a rendering backend must implement."""

    def begin(self, width_mm: float, height_mm: float) -> None: ...
    def rect(self, prim: Rect) -> None: ...
    def line(self, prim: Line) -> None: ...
    def polyline(self, prim: PolyLine) -> None: ...
    def text(self, prim: Text) -> None: ...
    def symbol(self, prim: SymbolPrim) -> None: ...
    def end(self) -> None: ...


def render(draw_list: DrawList, painter: Painter) -> None:
    """Walk a draw list, dispatching each primitive to the backend."""
    painter.begin(draw_list.width_mm, draw_list.height_mm)
    for item in draw_list.items:
        if isinstance(item, Rect):
            painter.rect(item)
        elif isinstance(item, Line):
            painter.line(item)
        elif isinstance(item, PolyLine):
            painter.polyline(item)
        elif isinstance(item, Text):
            painter.text(item)
        elif isinstance(item, SymbolPrim):
            painter.symbol(item)
        else:  # pragma: no cover - exhaustive over the Primitive union
            raise TypeError(f"Unknown primitive type: {type(item).__name__}")
    painter.end()
