"""Shared page-furniture builders.

Every one of these is a pure function returning primitives. The preview, the
tiled PDF and the continuous PDF all call the same functions, which is why the
screen and the print cannot disagree about where the ruler ticks fall.
"""

from __future__ import annotations

from dataclasses import replace

from aops.core.cell import CellSpec
from aops.core.config import AopsConfig, PrintConfig
from aops.core.drawlist import (
    Line,
    PolyLine,
    Primitive,
    Rect,
    SymbolPrim,
    Text,
)
from aops.core.enums import HrPosition, SegmentKind
from aops.core.geometry import PageLayout
from aops.core.layout import style as S
from aops.core.matrix import ModuleMatrix
from aops.core.ruler import RulerSpec, TickClass, ticks_between
from aops.core.text_metrics import DEFAULT_METRICS, TextMeasurer
from aops.core.units import mm_to_um, um_to_mm

_TICK_STYLE = {
    TickClass.MINOR: S.RULER_MINOR,
    TickClass.MEDIUM: S.RULER_MEDIUM,
    TickClass.MAJOR: S.RULER_MAJOR,
    TickClass.EMPHASIS: S.RULER_EMPHASIS,
}


def ruler_elements(
    x0_mm: float,
    x1_mm: float,
    y_mm: float,
    *,
    spec: RulerSpec | None = None,
    origin_mm: float = 0.0,
    measurer: TextMeasurer | None = None,
    label_gap_mm: float = 1.2,
) -> list[Primitive]:
    """An engineering ruler spanning absolute strip positions x0..x1.

    Ticks are generated in absolute strip coordinates and then offset to the
    local drawing origin, so a ruler continues seamlessly across a page break
    with no duplicated or missing tick at the seam.
    """
    spec = spec or RulerSpec()
    measurer = measurer or DEFAULT_METRICS
    # Drawn at LOCAL x: the content origin of every page is its own x0, so a
    # tick at absolute position `t` sits at `t - x0` locally. The first
    # version drew at absolute x, which was invisible on page one (x0 = 0,
    # the only page anyone had printed) and pushed every later page's ruler
    # off the sheet - the docstring promised this offset; now it exists.
    out: list[Primitive] = [Line(0.0, y_mm, x1_mm - x0_mm, y_mm, S.RULER_BASELINE)]

    for tick in ticks_between(mm_to_um(x0_mm), mm_to_um(x1_mm), spec, origin_um=mm_to_um(origin_mm)):
        tx = um_to_mm(tick.x_um) - x0_mm
        length = spec.length_for(tick.cls)
        out.append(Line(tx, y_mm, tx, y_mm + length, _TICK_STYLE[tick.cls]))
        if tick.label is not None:
            width = measurer.width_mm(tick.label, S.RULER_LABEL.role, S.RULER_LABEL.size_pt)
            out.append(
                Text(
                    tx - width / 2.0,
                    y_mm + length + label_gap_mm + S.RULER_LABEL.size_pt * 0.35,
                    tick.label,
                    S.RULER_LABEL,
                )
            )
    return out


def calibration_elements(
    x_mm: float,
    y_mm: float,
    printing: PrintConfig,
    *,
    measurer: TextMeasurer | None = None,
) -> list[Primitive]:
    """The printed calibration bar and the instructions that close the loop.

    The bar is drawn at its nominal length in design space; printer scaling then
    multiplies it along with everything else. So the operator's loop is:
    print at 100 %, measure the bar, set scaling to ``200 / measured x 100``,
    reprint - at which point the bar lands at exactly 200 mm and so does the
    pitch. The second instruction line is what makes that loop discoverable
    without reading the manual.
    """
    measurer = measurer or DEFAULT_METRICS
    length = printing.calibration_length_mm
    bar_h = 3.0
    out: list[Primitive] = [
        Rect(x_mm, y_mm, length, bar_h, S.CALIBRATION_BAR),
        # End ticks give an unambiguous measuring datum at each end.
        Line(x_mm, y_mm - 1.5, x_mm, y_mm + bar_h + 1.5, S.CALIBRATION_TICK),
        Line(x_mm + length, y_mm - 1.5, x_mm + length, y_mm + bar_h + 1.5, S.CALIBRATION_TICK),
    ]

    label = f"|<--  {length:.1f} mm  -->|"
    lw = measurer.width_mm(label, S.CALIBRATION_LABEL.role, S.CALIBRATION_LABEL.size_pt)
    out.append(Text(x_mm + (length - lw) / 2.0, y_mm + bar_h * 0.72, label, S.CALIBRATION_LABEL))

    warn = f"THIS BAR MUST MEASURE EXACTLY {length:.0f} mm"
    ww = measurer.width_mm(warn, S.CALIBRATION_WARNING.role, S.CALIBRATION_WARNING.size_pt)
    out.append(Text(x_mm + (length - ww) / 2.0, y_mm + bar_h + 5.0, warn, S.CALIBRATION_WARNING))

    hint = (
        f"If not: set Printer Scaling = {length:.0f} / (measured mm) x 100 %.   "
        f"Printed at {printing.scale_percent:.3f} % scale."
    )
    hw = measurer.width_mm(hint, S.CALIBRATION_HINT.role, S.CALIBRATION_HINT.size_pt)
    out.append(Text(x_mm + (length - hw) / 2.0, y_mm + bar_h + 9.0, hint, S.CALIBRATION_HINT))
    return out


def registration_marks(sheet_w_mm: float, sheet_h_mm: float, printing: PrintConfig) -> list[Primitive]:
    """Corner crosshairs in **physical sheet space**.

    These align one sheet against another, so they must land at fixed positions
    on the paper. Scaling them with the content would defeat their entire
    purpose, which is why they live in the sheet draw list.
    """
    if not printing.registration_marks:
        return []
    size = printing.registration_mark_size_mm
    inset = 6.0
    out: list[Primitive] = []
    for cx, cy in (
        (inset, inset),
        (sheet_w_mm - inset, inset),
        (inset, sheet_h_mm - inset),
        (sheet_w_mm - inset, sheet_h_mm - inset),
    ):
        out.append(Line(cx - size / 2, cy, cx + size / 2, cy, S.REGISTRATION))
        out.append(Line(cx, cy - size / 2, cx, cy + size / 2, S.REGISTRATION))
        out.append(
            PolyLine(
                (
                    (cx - size / 3, cy - size / 3),
                    (cx + size / 3, cy - size / 3),
                    (cx + size / 3, cy + size / 3),
                    (cx - size / 3, cy + size / 3),
                ),
                S.REGISTRATION,
                close=True,
            )
        )
    return out


def cut_marks(
    x_mm: float, band_top_mm: float, band_bottom_mm: float, printing: PrintConfig
) -> list[Primitive]:
    """Trim indicators at a splice position, in content space."""
    if not printing.cut_marks:
        return []
    length = printing.cut_mark_length_mm
    out: list[Primitive] = [
        Line(x_mm, band_top_mm - length, x_mm, band_top_mm, S.CUT_MARK),
        Line(x_mm, band_bottom_mm, x_mm, band_bottom_mm + length, S.CUT_MARK),
    ]
    if printing.cut_line_across_strip:
        # Off by default: ink drawn through the strip band can confuse a reader.
        out.append(Line(x_mm, band_top_mm, x_mm, band_bottom_mm, S.CUT_LINE))
    return out


def splice_joints(
    page: PageLayout,
    total_pages: int,
    band_top_mm: float,
    band_bottom_mm: float,
    printing: PrintConfig,
    *,
    measurer: TextMeasurer | None = None,
) -> list[Primitive]:
    """Labelled trim boundaries where this row meets its neighbours.

    Every inter-row joint prints the same number on both mating edges:
    "SPLICE 3" at the right edge of row 3 and again at the left edge of
    row 4. The installer cuts along both lines and joins them - the
    matching numbers say which edge mates with which, and the line itself
    is the guide that keeps the pitch true across the joint. The strip's
    outer ends carry START and END instead, so every cut-out row has an
    explicit boundary at both ends.

    The line is dashed through the band (solid ink beside a code could
    read as structure) and solid in the short overhangs above and below.
    It sits exactly on the cell boundary, which the splice guarantee
    keeps in white and the margin keeps a full quiet zone clear of any
    symbol - and a correct cut removes the line entirely.

    Gated on its own switch rather than on ``printing.cut_marks``: the
    Labelled style keeps cut marks off but still has a strip to assemble.
    Only the Plain style - symbols and nothing else, by contract - turns
    these off.
    """
    if not printing.splice_labels:
        return []
    measurer = measurer or DEFAULT_METRICS
    length_mm = um_to_mm(page.content_length_um)
    n = page.strip_page_number
    overhang = 2.2
    out: list[Primitive] = []

    def edge(x: float, label: str, *, align_right: bool) -> None:
        out.append(Line(x, band_top_mm - overhang, x, band_top_mm, S.CUT_MARK))
        out.append(Line(x, band_top_mm, x, band_bottom_mm, S.CUT_LINE))
        out.append(Line(x, band_bottom_mm, x, band_bottom_mm + overhang, S.CUT_MARK))
        w = measurer.width_mm(label, S.RULER_LABEL.role, S.RULER_LABEL.size_pt)
        tx = x - w - 1.0 if align_right else x + 1.0
        out.append(Text(tx, band_top_mm - 0.8, label, S.RULER_LABEL))

    edge(0.0, "START" if n == 1 else f"SPLICE {n - 1}", align_right=False)
    edge(length_mm, "END" if n == total_pages else f"SPLICE {n}", align_right=True)
    return out


def alignment_arrows(
    x0_mm: float, x1_mm: float, y_mm: float, printing: PrintConfig, *, forward: bool = True
) -> list[Primitive]:
    """Direction-of-travel arrows so a tile cannot be mounted backwards."""
    if not printing.alignment_arrows:
        return []
    out: list[Primitive] = []
    head = 2.2
    span = x1_mm - x0_mm
    if span <= 4 * head:
        return out
    for frac in (0.25, 0.75):
        cx = x0_mm + span * frac
        tip = cx + (head if forward else -head)
        tail = cx - (head if forward else -head)
        out.append(Line(tail - head, y_mm, tail, y_mm, S.ARROW))
        out.append(
            PolyLine(
                ((tail, y_mm - head * 0.6), (tip, y_mm), (tail, y_mm + head * 0.6)),
                S.ARROW,
                close=True,
            )
        )
    return out


def strip_cells(
    page: PageLayout,
    cell: CellSpec,
    matrices: dict[str, ModuleMatrix],
    payload_of: dict[int, str],
    cfg: AopsConfig,
    band_top_mm: float,
    *,
    measurer: TextMeasurer | None = None,
) -> list[Primitive]:
    """Symbols and their human-readable text for one page of the strip."""
    measurer = measurer or DEFAULT_METRICS
    out: list[Primitive] = []
    # Honour the configured human-readable size rather than the style default.
    hr_style = replace(S.HUMAN_READABLE, size_pt=cfg.output.hr_font_pt)

    for placed in page.placed:
        seg = placed.segment
        if seg.kind is not SegmentKind.CELL or seg.index is None:
            continue
        payload = payload_of.get(seg.index)
        if payload is None:
            continue
        matrix = matrices.get(payload)
        if matrix is None:
            continue

        x_mm = um_to_mm(placed.x_um + cell.symbol_x_offset_um)
        y_mm = band_top_mm + um_to_mm(cell.symbol_y_offset_um)
        out.append(SymbolPrim(x_mm, y_mm, cell.symbol_mm, matrix))

        if cfg.output.human_readable:
            width = measurer.width_mm(payload, hr_style.role, cfg.output.hr_font_pt)
            centre = um_to_mm(placed.x_um + cell.pitch_um / 2.0)
            tx = centre - width / 2.0
            if cfg.output.hr_position is HrPosition.BELOW:
                ty = y_mm + cell.symbol_mm + cfg.output.hr_font_pt * 0.50
            else:
                ty = y_mm - cfg.output.hr_font_pt * 0.20
            out.append(Text(tx, ty, payload, hr_style))
    return out


def header_elements(
    page_label: str,
    cfg: AopsConfig,
    width_mm: float,
    y_mm: float,
    *,
    measurer: TextMeasurer | None = None,
) -> list[Primitive]:
    """Title band identifying the machine, project and strip."""
    measurer = measurer or DEFAULT_METRICS
    p = cfg.project
    title = "ABSOLUTE OPTICAL POSITION STRIP"
    out: list[Primitive] = [Text(0.0, y_mm, title, S.HEADER_TITLE)]

    bits = []
    if p.machine:
        bits.append(f"MACHINE {p.machine}")
    if p.project:
        bits.append(f"PROJECT {p.project}")
    if p.strip_id:
        bits.append(f"STRIP {p.strip_id}")
    right = "   ".join(bits) if bits else page_label
    rw = measurer.width_mm(right, S.HEADER_FIELD.role, S.HEADER_FIELD.size_pt)
    out.append(Text(max(0.0, width_mm - rw), y_mm, right, S.HEADER_FIELD))
    out.append(Line(0.0, y_mm + 1.6, width_mm, y_mm + 1.6, S.RULE_LINE))
    return out


def footer_elements(
    left: str,
    right: str,
    width_mm: float,
    y_mm: float,
    *,
    measurer: TextMeasurer | None = None,
) -> list[Primitive]:
    """Footer band carrying page, code range, absolute distance and fingerprint."""
    measurer = measurer or DEFAULT_METRICS
    out: list[Primitive] = [
        Line(0.0, y_mm - 2.4, width_mm, y_mm - 2.4, S.RULE_LINE),
        Text(0.0, y_mm, left, S.FOOTER),
    ]
    rw = measurer.width_mm(right, S.FOOTER.role, S.FOOTER.size_pt)
    out.append(Text(max(0.0, width_mm - rw), y_mm, right, S.FOOTER))
    return out


def page_footer_text(
    page: PageLayout,
    total_pages: int,
    cfg: AopsConfig,
    fingerprint: str,
    position_range: tuple[float, float],
) -> tuple[str, str]:
    """Build the two footer strings for a strip page.

    The absolute X range is the load-bearing part: it is what lets an installer
    position each tile against a measured datum instead of butting it against
    the previous one, which is the difference between bounded and accumulating
    error over a long strip.
    """
    codes = (
        f"CODES {page.first_index}-{page.last_index}"
        if page.first_index is not None
        else "CODES (none)"
    )
    left = (
        f"SHEET {page.strip_page_number:02d}/{total_pages:02d}   {codes}   "
        f"X {page.strip_x0_mm:.1f}-{page.strip_x1_mm:.1f} mm   "
        f"POS {position_range[0]:.1f}-{position_range[1]:.1f} mm"
    )
    right = f"REV {cfg.project.revision or '-'}   {fingerprint}"
    return left, right
