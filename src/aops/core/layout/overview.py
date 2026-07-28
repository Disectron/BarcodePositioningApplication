"""The miniature full-strip overview.

Built entirely from `PageLayout` metadata - **no symbols are encoded and none
are drawn**. For a 39-page strip that is roughly a hundred primitives and takes
well under a millisecond, so the overview can be rebuilt whenever pagination
changes without any effect on interactive responsiveness.

Code density is suggested by a hatched band rather than by real symbols. Drawing
421 actual Data Matrix codes at two pixels each would be slower, and would look
like noise anyway.
"""

from __future__ import annotations

from aops.core.config import AopsConfig
from aops.core.drawlist import DrawList, Line, Primitive, Rect, Text
from aops.core.layout import style as S
from aops.core.stats import DerivedGeometry
from aops.core.text_metrics import DEFAULT_METRICS, TextMeasurer

BAR_HEIGHT_MM = 10.0
LABEL_BAND_MM = 5.0
HATCH_PITCH_MM = 1.6


def compose_overview(
    cfg: AopsConfig,
    derived: DerivedGeometry,
    *,
    target_width_mm: float = 260.0,
    highlight_page: int | None = None,
    measurer: TextMeasurer | None = None,
) -> DrawList:
    """Compose a not-to-scale overview of the whole strip."""
    measurer = measurer or DEFAULT_METRICS
    total_mm = derived.total_length_mm
    height = BAR_HEIGHT_MM + LABEL_BAND_MM * 2

    if total_mm <= 0 or not derived.pages:
        return DrawList(target_width_mm, height, ())

    scale = target_width_mm / total_mm
    items: list[Primitive] = []
    top = LABEL_BAND_MM

    for page in derived.pages:
        x0 = page.strip_x0_mm * scale
        x1 = page.strip_x1_mm * scale
        w = max(x1 - x0, 0.2)

        items.append(Rect(x0, top, w, BAR_HEIGHT_MM, S.OVERVIEW_PAGE))

        # Hatched band standing in for code density.
        if page.cell_count:
            hatch_x = x0 + HATCH_PITCH_MM / 2
            while hatch_x < x1 - HATCH_PITCH_MM / 4:
                items.append(
                    Line(hatch_x, top + 2.0, hatch_x, top + BAR_HEIGHT_MM - 2.0, S.FAINT_RULE)
                )
                hatch_x += HATCH_PITCH_MM

        # Splice tick at the page boundary.
        items.append(Line(x1, top - 1.5, x1, top + BAR_HEIGHT_MM + 1.5, S.OVERVIEW_SPLICE))

        label = str(page.strip_page_number)
        lw = measurer.width_mm(label, S.OVERVIEW_LABEL.role, S.OVERVIEW_LABEL.size_pt)
        if w > lw * 1.4:
            items.append(
                Text(x0 + (w - lw) / 2, top + BAR_HEIGHT_MM / 2 + 1.0, label, S.OVERVIEW_LABEL)
            )

        if highlight_page is not None and page.strip_page_number == highlight_page:
            items.append(Rect(x0, top - 0.8, w, BAR_HEIGHT_MM + 1.6, S.OVERVIEW_HIGHLIGHT))

    # Distance scale beneath, labelled in metres for a strip of any length.
    axis_y = top + BAR_HEIGHT_MM + 2.6
    items.append(Line(0.0, axis_y, target_width_mm, axis_y, S.RULE_LINE))
    steps = 6
    for i in range(steps + 1):
        x = target_width_mm * i / steps
        value_m = total_mm * i / steps / 1000.0
        items.append(Line(x, axis_y, x, axis_y + 1.4, S.RULER_MEDIUM))
        label = f"{value_m:.2f} m"
        lw = measurer.width_mm(label, S.OVERVIEW_LABEL.role, S.OVERVIEW_LABEL.size_pt)
        items.append(Text(min(max(x - lw / 2, 0.0), target_width_mm - lw),
                          axis_y + 4.2, label, S.OVERVIEW_LABEL))

    summary = (
        f"{len(derived.pages)} sheets   {derived.code_count} codes   "
        f"{total_mm / 1000:.3f} m   {len(derived.pages) - 1} splices"
    )
    items.append(Text(0.0, 3.4, summary, S.OVERVIEW_LABEL))

    return DrawList(target_width_mm, axis_y + 6.0, tuple(items))
