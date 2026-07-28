"""Segments, pagination, and the splice guarantee.

This is the highest-risk module in the application. Everything downstream -
every exported PDF, every page footer, the whole installation procedure -
assumes the property proved here holds.

THE SPLICE GUARANTEE
--------------------
*Claim.* If the cell invariant ``symbol + 2 * quiet_zone <= pitch`` holds, then
every page boundary produced by `paginate` lies at least ``quiet_zone`` away
from any symbol ink.

*Proof.* The packer emits only whole segments, plus splits of segments marked
``splittable``, and only pure-white segments are ever marked splittable.
Therefore every boundary ``b`` is either

  (a) inside a LEAD/TRAIL/BLANK segment, which contains no ink at all, so the
      clearance is bounded only by the segment length; or
  (b) at a CELL/CELL junction, i.e. ``b = lead + j * pitch`` for integer ``j``.
      Symbol ink in cell ``j-1`` ends at ``b - margin_lr``; ink in cell ``j``
      begins at ``b + margin_lr``. The clearance is therefore ``margin_lr``,
      and ``margin_lr = (pitch - symbol) / 2 >= quiet_zone`` is exactly the cell
      invariant.  QED

At the default 25 mm / 10 mm geometry the clearance is 7.5 mm against a 1.0 mm
requirement - a 7.5x margin on cutting accuracy. That figure is printed on the
installation guide.

`verify_splices` re-derives the property **independently**, from the placed
geometry rather than from the packer's own assumptions. It is asserted both in
the test suite and at export time. A packer bug must never be able to silently
ship a strip with a symbol cut in half.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aops.core.cell import CellSpec
from aops.core.config import AopsConfig
from aops.core.enums import PitchMode, SegmentKind
from aops.core.errors import GeometryError
from aops.core.positions import code_count, code_indices, ordinal_of
from aops.core.units import mm_to_um, um_floor, um_to_mm


@dataclass(frozen=True, slots=True)
class Segment:
    """One indivisible (or freely divisible) piece of the strip along X.

    `splittable` is the load-bearing field: it is True only for segments that
    contain no ink whatsoever. Any future feature that draws something - a
    second track, a camera fiducial, a CRC block - registers as a non-splittable
    segment and inherits the splice guarantee without touching the packer.
    """

    kind: SegmentKind
    length_um: int
    index: int | None = None
    ordinal: int | None = None
    splittable: bool = False

    def split(self, head_um: int) -> tuple[Segment, Segment]:
        """Divide into a head of `head_um` and the remainder.

        Only valid on splittable (white) segments.
        """
        if not self.splittable:
            raise GeometryError(
                f"Refusing to split an atomic {self.kind.value} segment - this "
                f"would cut a symbol, quiet zone or margin."
            )
        if not 0 < head_um < self.length_um:
            raise GeometryError(
                f"Split point {head_um} um outside segment of {self.length_um} um."
            )
        head = Segment(self.kind, head_um, self.index, self.ordinal, True)
        tail = Segment(self.kind, self.length_um - head_um, self.index, self.ordinal, True)
        return head, tail


@dataclass(frozen=True, slots=True)
class PlacedSegment:
    """A segment together with its X offset inside a page's usable area."""

    segment: Segment
    x_um: int


@dataclass(frozen=True, slots=True)
class PageLayout:
    """Everything needed to draw one strip page and label it correctly."""

    strip_page_number: int  # 1-based, among strip pages only
    placed: tuple[PlacedSegment, ...]
    strip_x0_um: int  # X of this page's left edge within the whole strip
    strip_x1_um: int
    first_index: int | None
    last_index: int | None

    @property
    def content_length_um(self) -> int:
        return self.strip_x1_um - self.strip_x0_um

    @property
    def strip_x0_mm(self) -> float:
        return um_to_mm(self.strip_x0_um)

    @property
    def strip_x1_mm(self) -> float:
        return um_to_mm(self.strip_x1_um)

    @property
    def cells(self) -> tuple[PlacedSegment, ...]:
        return tuple(p for p in self.placed if p.segment.kind is SegmentKind.CELL)

    @property
    def cell_count(self) -> int:
        return len(self.cells)


def build_segments(cfg: AopsConfig, cell: CellSpec) -> tuple[Segment, ...]:
    """Lay the whole strip out as a flat sequence of segments.

    Order is: leading margin, then one segment per pitch slot, then the trailing
    margin. Under PER_INDEX pitch mode, skipped indices become BLANK segments so
    that the literal ``Position = Index x Pitch`` relationship is preserved.
    """
    segments: list[Segment] = []

    lead_um = mm_to_um(cfg.printing.leading_margin_mm)
    if lead_um > 0:
        segments.append(Segment(SegmentKind.LEAD, lead_um, splittable=True))

    pos = cfg.position
    printed = set(code_indices(pos))

    if code_count(pos) > 0:
        if pos.pitch_mode is PitchMode.PER_CELL:
            for ordinal, index in enumerate(code_indices(pos)):
                segments.append(
                    Segment(SegmentKind.CELL, cell.pitch_um, index=index, ordinal=ordinal)
                )
        else:
            for offset in range(pos.end_index - pos.start_index + 1):
                index = pos.start_index + offset
                if index in printed:
                    segments.append(
                        Segment(
                            SegmentKind.CELL,
                            cell.pitch_um,
                            index=index,
                            ordinal=ordinal_of(index, pos),
                        )
                    )
                else:
                    # A blank slot still occupies a full pitch, but carries no
                    # ink, so it may be cut anywhere.
                    segments.append(
                        Segment(SegmentKind.BLANK, cell.pitch_um, index=None, splittable=True)
                    )

    trail_um = mm_to_um(cfg.printing.trailing_margin_mm)
    if trail_um > 0:
        segments.append(Segment(SegmentKind.TRAIL, trail_um, splittable=True))

    return tuple(segments)


def usable_width_um(cfg: AopsConfig) -> int:
    """Design-space width available on one sheet, in micrometres.

    Printer scaling multiplies emitted artwork, so raising the scale *shrinks*
    the design-space capacity of a fixed sheet. This is why scaling cannot be a
    late emit-time detail: at A4 landscape with 10 mm margins, k=1.000 fits 11
    cells per page but k=1.010 fits only 10, turning a 39-page job into 43.

    Page margins are positions on physical paper and are therefore not scaled.
    """
    scale = cfg.printing.scale_factor
    if scale <= 0:
        raise GeometryError(f"Printer scaling must be positive (got {cfg.printing.scale_percent}%).")
    return um_floor(cfg.paper.usable_width_mm() / scale)


def cells_per_page(cell: CellSpec, usable_um: int) -> int:
    """How many whole cells fit across one page."""
    if cell.pitch_um <= 0:
        return 0
    return max(0, usable_um // cell.pitch_um)


def paginate(segments: Sequence[Segment], usable_um: int) -> tuple[PageLayout, ...]:
    """Greedy first-fit packing of segments into pages.

    Atomic (inked) segments are never split. White segments are split freely to
    fill out a page. All comparisons are exact integer arithmetic - there is no
    epsilon anywhere in this function, which is the point of working in
    micrometres.

    Raises `GeometryError` if a single atomic segment cannot fit on an empty
    page. Validation rule PAG-001 fires before the user can reach this, but the
    exception remains the last line of defence for the CLI and tests.
    """
    if usable_um <= 0:
        raise GeometryError(
            f"Usable page width is {um_to_mm(usable_um):.3f} mm. Reduce page margins, "
            f"increase the page size, or reduce printer scaling."
        )

    pages: list[PageLayout] = []
    current: list[PlacedSegment] = []
    used_um = 0
    strip_cursor_um = 0
    page_start_um = 0

    def flush() -> None:
        nonlocal current, used_um, page_start_um
        if not current:
            return
        cells = [p.segment for p in current if p.segment.kind is SegmentKind.CELL]
        pages.append(
            PageLayout(
                strip_page_number=len(pages) + 1,
                placed=tuple(current),
                strip_x0_um=page_start_um,
                strip_x1_um=page_start_um + used_um,
                first_index=cells[0].index if cells else None,
                last_index=cells[-1].index if cells else None,
            )
        )
        page_start_um += used_um
        current = []
        used_um = 0

    for segment in segments:
        remaining = segment

        while True:
            if used_um + remaining.length_um <= usable_um:
                current.append(PlacedSegment(remaining, used_um))
                used_um += remaining.length_um
                strip_cursor_um += remaining.length_um
                break

            free = usable_um - used_um
            if remaining.splittable and free > 0:
                head, tail = remaining.split(free)
                current.append(PlacedSegment(head, used_um))
                used_um += head.length_um
                strip_cursor_um += head.length_um
                flush()
                remaining = tail
                continue

            if not current:
                # An empty page could not accommodate this segment at all.
                raise GeometryError(
                    f"A single {remaining.kind.value} segment of "
                    f"{um_to_mm(remaining.length_um):.3f} mm does not fit in the usable "
                    f"page width of {um_to_mm(usable_um):.3f} mm. Increase the page size, "
                    f"reduce the cell pitch, reduce page margins, or reduce printer scaling."
                )

            flush()
            # Retry the same segment on a fresh page.

    flush()
    return tuple(pages)


def verify_splices(pages: Sequence[PageLayout], cell: CellSpec) -> tuple[str, ...]:
    """Independently confirm that no page boundary cuts symbol ink.

    This deliberately re-derives the property from the *placed* geometry rather
    than trusting the packer. It returns a tuple of human-readable violations,
    which must be empty. Called from the test suite and again at export time.
    """
    violations: list[str] = []
    required_um = cell.quiet_zone_um

    for page in pages:
        if not page.placed:
            violations.append(f"Page {page.strip_page_number} is empty.")
            continue

        # 1. Nothing may overflow the page.
        total = sum(p.segment.length_um for p in page.placed)
        if total != page.content_length_um:
            violations.append(
                f"Page {page.strip_page_number}: placed length {total} um disagrees with "
                f"declared span {page.content_length_um} um."
            )

        # 2. Segments must be contiguous and in order.
        cursor = 0
        for placed in page.placed:
            if placed.x_um != cursor:
                violations.append(
                    f"Page {page.strip_page_number}: segment at {placed.x_um} um breaks "
                    f"contiguity (expected {cursor} um)."
                )
            cursor += placed.segment.length_um

        # 3. The leading and trailing edges of the page must clear symbol ink.
        #    A cell sitting flush against a page edge is fine - its own L/R
        #    margin supplies the clearance - so the only question is whether that
        #    margin is wide enough for the quiet zone.
        first, last = page.placed[0], page.placed[-1]
        edge_cells = (
            (first, "leading", "before"),
            (last, "trailing", "after"),
        )
        for placed, edge, preposition in edge_cells:
            if placed.segment.kind is SegmentKind.CELL and cell.margin_lr_um < required_um:
                violations.append(
                    f"Page {page.strip_page_number}: {edge} cut leaves "
                    f"{um_to_mm(cell.margin_lr_um):.3f} mm {preposition} symbol ink, "
                    f"needs {um_to_mm(required_um):.3f} mm."
                )

        # 4. No CELL segment may have been divided. A whole cell is exactly one
        #    pitch long; anything shorter means the packer split one.
        for placed in page.placed:
            if placed.segment.kind is SegmentKind.CELL and placed.segment.length_um != cell.pitch_um:
                violations.append(
                    f"Page {page.strip_page_number}: cell index {placed.segment.index} has "
                    f"length {placed.segment.length_um} um, expected a full pitch of "
                    f"{cell.pitch_um} um - a symbol has been split."
                )

    # 5. Page spans must tile the strip exactly, with no gaps or overlaps.
    for prev, nxt in zip(pages, pages[1:], strict=False):
        if prev.strip_x1_um != nxt.strip_x0_um:
            violations.append(
                f"Pages {prev.strip_page_number}/{nxt.strip_page_number} do not abut: "
                f"{prev.strip_x1_um} um then {nxt.strip_x0_um} um."
            )

    return tuple(violations)


def total_strip_length_um(segments: Sequence[Segment]) -> int:
    """Total length of the strip including lead and trail margins."""
    return sum(s.length_um for s in segments)
