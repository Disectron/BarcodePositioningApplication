"""PDF export - tiled sheets and the continuous strip.

Both exporters run with no Qt present, which is what allows the whole output
path to be tested (and driven from the CLI) headlessly.

Two safety measures run at export time rather than only in tests:

* `verify_splices` is re-run on the final pagination. If a packer bug ever let a
  symbol be cut, the export aborts rather than writing the file.
* Symbols are decode-verified according to `OutputConfig.verify_mode`. Sampling
  sixteen codes costs about half a second on a 421-code strip and turns "the PDF
  is probably right" into evidence.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from reportlab.pdfgen import canvas as rl_canvas

from aops.core.config import AopsConfig
from aops.core.drawlist import DrawList, render
from aops.core.enums import ContinuousStrategy, VerifyMode
from aops.core.errors import AopsError, GeometryError
from aops.core.geometry import verify_splices
from aops.core.layout.guide import compose_guide_pages
from aops.core.layout.strip import compose_continuous, compose_strip_page
from aops.core.matrix import ModuleMatrix
from aops.core.project_io import config_fingerprint
from aops.core.stats import DerivedGeometry
from aops.core.units import MM2PT, mm_to_pt
from aops.render.pdf.backend import PdfPainter
from aops.render.pdf.userunit import ensure_pdf_16, user_unit
from aops.symbols.cache import SymbolCache

#: (done, total, phase)
ProgressFn = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class ExportResult:
    """What an export produced."""

    paths: tuple[Path, ...]
    page_count: int
    verified_count: int
    total_bytes: int

    @property
    def path(self) -> Path:
        return self.paths[0]


class ExportCancelled(AopsError):
    """Raised when the user cancels; the partial file is removed."""


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _begin_content(
    canvas,  # type: ignore[no-untyped-def]
    cfg: AopsConfig,
    page_h_pt: float,
    *,
    content_h_mm: float | None = None,
) -> None:
    """Establish the content transform: design mm, Y down, inside the margins.

    Printer compensation `k` is applied here so that every drawn dimension -
    including the calibration bar - is scaled identically. That is what makes
    the measure-and-correct loop converge.

    When `content_h_mm` is given and the content is shorter than the usable
    height, the block is centred vertically. A strip band pinned to the top of
    an otherwise blank sheet reads as a mistake; centring it also puts the
    calibration bar somewhere a steel rule can reach comfortably.
    """
    k = cfg.printing.scale_factor
    top_mm = cfg.paper.margin_top_mm
    if content_h_mm is not None:
        slack = cfg.paper.usable_height_mm() - content_h_mm * k
        if slack > 0:
            top_mm += slack / 2.0
    canvas.saveState()
    canvas.translate(mm_to_pt(cfg.paper.margin_left_mm), page_h_pt - mm_to_pt(top_mm))
    canvas.scale(k * MM2PT, -k * MM2PT)


def _begin_sheet(canvas, page_h_pt: float) -> None:  # type: ignore[no-untyped-def]
    """Establish the sheet transform: physical mm, Y down, NOT scaled.

    Registration marks align one sheet against another, so they must sit at
    fixed physical positions regardless of printer compensation.
    """
    canvas.saveState()
    canvas.translate(0, page_h_pt)
    canvas.scale(MM2PT, -MM2PT)


def _draw(canvas, draw_list: DrawList, cache: SymbolCache | None) -> None:  # type: ignore[no-untyped-def]
    render(draw_list, PdfPainter(canvas, rect_cache=cache))


def _verify_symbols(
    cfg: AopsConfig,
    derived: DerivedGeometry,
    cache: SymbolCache,
    matrices: dict[str, ModuleMatrix],
    progress: ProgressFn | None,
) -> int:
    """Decode-verify exported symbols according to the configured mode."""
    mode = cfg.output.verify_mode
    if mode is VerifyMode.OFF or not matrices:
        return 0

    encoder = cache.encoder_for(cfg.symbol.symbology)
    verify = getattr(encoder, "verify_roundtrip", None)
    if verify is None:
        return 0

    payloads = list(matrices)
    if mode is VerifyMode.SAMPLE:
        n = max(2, min(cfg.output.verify_sample_count, len(payloads)))
        # First, last, and an even spread between - the ends are where an
        # off-by-one in the index range would show up.
        step = max(1, (len(payloads) - 1) // max(n - 1, 1))
        chosen = payloads[::step][: n - 1]
        if payloads[-1] not in chosen:
            chosen.append(payloads[-1])
        payloads = chosen

    for i, payload in enumerate(payloads, start=1):
        if not verify(matrices[payload]):
            raise AopsError(
                f"Decode verification failed for payload {payload!r}. The exported "
                f"symbol would not read correctly; export aborted."
            )
        if progress is not None and (i % 4 == 0 or i == len(payloads)):
            progress(i, len(payloads), "verifying")
    return len(payloads)


def _prepare(
    cfg: AopsConfig,
    derived: DerivedGeometry,
    cache: SymbolCache,
    progress: ProgressFn | None,
    cancel: Event | None,
) -> dict[str, ModuleMatrix]:
    """Encode every payload up front so the drawing phase is pure cache hits."""
    if derived.pages:
        violations = verify_splices(derived.pages, derived.cell)
        if violations:
            raise GeometryError(
                "Refusing to export: the pagination would cut a symbol.\n  "
                + "\n  ".join(violations[:5])
            )

    payloads = list(dict.fromkeys(derived.payloads))
    total = len(payloads)
    matrices: dict[str, ModuleMatrix] = {}
    for i, payload in enumerate(payloads, start=1):
        if cancel is not None and cancel.is_set():
            raise ExportCancelled("Export cancelled.")
        matrices[payload] = cache.get(cfg.symbol.symbology, payload)
        if progress is not None and (i % 25 == 0 or i == total):
            progress(i, total, "encoding")
    return matrices


def export_tiled(
    cfg: AopsConfig,
    derived: DerivedGeometry,
    cache: SymbolCache,
    out_path: str | os.PathLike[str],
    *,
    progress: ProgressFn | None = None,
    cancel: Event | None = None,
) -> ExportResult:
    """Write the tiled A-series PDF: guide page then strip sheets."""
    path = Path(out_path)
    if not derived.pages:
        raise GeometryError("There are no pages to export.")

    matrices = _prepare(cfg, derived, cache, progress, cancel)
    fingerprint = config_fingerprint(cfg)
    stamp = _timestamp()

    sheet_w_mm, sheet_h_mm = cfg.paper.sheet_size_mm()
    page_size = (mm_to_pt(sheet_w_mm), mm_to_pt(sheet_h_mm))
    page_h_pt = page_size[1]

    c = rl_canvas.Canvas(str(path), pagesize=page_size)
    c.setTitle(f"AOPS position strip - {cfg.project.strip_id or cfg.project.machine or 'untitled'}")
    c.setAuthor(cfg.project.engineer or "AOPS")
    c.setSubject(f"Absolute optical position strip, revision {cfg.project.revision}")
    c.setCreator("AOPS - Absolute Optical Position Strip Generator")

    written = 0

    if cfg.output.instruction_page:
        # The guide flows onto extra sheets rather than truncating; dropping the
        # verification and warning sections off the bottom would be far worse
        # than spending another sheet of paper.
        for guide_page in compose_guide_pages(cfg, derived, fingerprint, stamp):
            _begin_content(c, cfg, page_h_pt)
            _draw(c, guide_page, cache)
            c.restoreState()
            c.showPage()
            written += 1

    total_pages = len(derived.pages)
    for n, page in enumerate(derived.pages, start=1):
        if cancel is not None and cancel.is_set():
            c.save()
            path.unlink(missing_ok=True)
            raise ExportCancelled("Export cancelled.")

        lists = compose_strip_page(page, cfg, derived, matrices, fingerprint)

        _begin_content(c, cfg, page_h_pt, content_h_mm=lists.content.height_mm)
        _draw(c, lists.content, cache)
        c.restoreState()

        if lists.sheet.items:
            _begin_sheet(c, page_h_pt)
            _draw(c, lists.sheet, cache)
            c.restoreState()

        c.showPage()
        written += 1
        if progress is not None:
            progress(n, total_pages, "drawing")

    c.save()

    verified = _verify_symbols(cfg, derived, cache, matrices, progress)
    return ExportResult(
        paths=(path,),
        page_count=written,
        verified_count=verified,
        total_bytes=path.stat().st_size,
    )


def export_continuous(
    cfg: AopsConfig,
    derived: DerivedGeometry,
    cache: SymbolCache,
    out_path: str | os.PathLike[str],
    *,
    progress: ProgressFn | None = None,
    cancel: Event | None = None,
) -> ExportResult:
    """Write the continuous strip: one page, no joins.

    Honours the configured oversize strategy - see `ContinuousStrategy`.
    """
    base = Path(out_path)
    matrices = _prepare(cfg, derived, cache, progress, cancel)
    fingerprint = config_fingerprint(cfg)
    spec = derived.continuous

    paths: list[Path] = []
    total_pages = 0

    for roll in range(spec.roll_count):
        if cancel is not None and cancel.is_set():
            for p in paths:
                p.unlink(missing_ok=True)
            raise ExportCancelled("Export cancelled.")

        if spec.roll_count > 1:
            path = base.with_name(f"{base.stem}_roll{roll + 1:02d}{base.suffix}")
        else:
            path = base

        lists = compose_continuous(cfg, derived, matrices, fingerprint, roll_index=roll)

        content_w_mm = lists.content.width_mm
        content_h_mm = max(lists.content.height_mm, spec.height_mm)
        true_w_pt = mm_to_pt(content_w_mm)
        true_h_pt = mm_to_pt(content_h_mm)

        if spec.strategy is ContinuousStrategy.USER_UNIT:
            unit = spec.user_unit
        else:
            # RAW_OVERSIZE writes the true size and accepts non-conformance;
            # SPLIT_ROLL is already within the limit by construction.
            unit = 1.0

        page_w_pt, page_h_pt = true_w_pt / unit, true_h_pt / unit

        with user_unit(unit):
            c = rl_canvas.Canvas(str(path), pagesize=(page_w_pt, page_h_pt))
            if unit > 1.0:
                ensure_pdf_16(c)
            c.setTitle(
                f"AOPS continuous strip - {cfg.project.strip_id or cfg.project.machine or 'untitled'}"
            )
            c.setCreator("AOPS - Absolute Optical Position Strip Generator")

            # Shrink into the reduced MediaBox, then draw in true design mm.
            c.saveState()
            c.scale(1.0 / unit, 1.0 / unit)
            c.translate(0, true_h_pt)
            k = cfg.printing.scale_factor
            c.scale(k * MM2PT, -k * MM2PT)
            _draw(c, lists.content, cache)
            c.restoreState()
            c.showPage()
            c.save()

        paths.append(path)
        total_pages += 1
        if progress is not None:
            progress(roll + 1, spec.roll_count, "drawing")

    verified = _verify_symbols(cfg, derived, cache, matrices, progress)
    return ExportResult(
        paths=tuple(paths),
        page_count=total_pages,
        verified_count=verified,
        total_bytes=sum(p.stat().st_size for p in paths),
    )


def export_all(
    cfg: AopsConfig,
    derived: DerivedGeometry,
    cache: SymbolCache,
    out_dir: str | os.PathLike[str],
    *,
    basename: str = "barcode_strip",
    progress: ProgressFn | None = None,
    cancel: Event | None = None,
) -> Sequence[ExportResult]:
    """Write whichever outputs the configuration selects."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    results: list[ExportResult] = []

    if cfg.output.tiled_pages:
        results.append(
            export_tiled(
                cfg, derived, cache,
                directory / f"{basename}_{cfg.paper.preset.value}_tiles.pdf",
                progress=progress, cancel=cancel,
            )
        )
    if cfg.output.continuous:
        results.append(
            export_continuous(
                cfg, derived, cache,
                directory / f"{basename}_continuous_signshop.pdf",
                progress=progress, cancel=cancel,
            )
        )
    return results
