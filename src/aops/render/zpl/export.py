"""ZPL export: the strip as native Zebra labels, plus raw network send.

The pieces are made by the same paginator that makes the tiled PDF pages -
the strip is repaginated onto *virtual paper as long as the printer allows*
(the smaller of the continuous piece cap and the printer's stated maximum
label length). That is not an implementation convenience, it is the safety
argument: page boundaries fall on cell boundaries, in white, and
`verify_splices` re-proves it for the actual pieces being written. The first
draft split pieces arithmetically like the continuous PDF's roll strategy,
which can land a boundary mid-code - the exact defect this whole tool exists
to prevent, hidden until a label tore through a symbol.

Each piece is rasterized at the printer's native dpi (no driver, viewer or
scaling setting between AOPS and the platen) and written as one `.zpl` file.
Pieces carry the same captions and numbered SPLICE boundaries as tiled
sheets, so joining them follows the printed instructions.

The guide page is deliberately absent: it is an A4 document for humans, not
a label. Print it from the PDF export.
"""

from __future__ import annotations

import dataclasses as dc
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from PIL import Image

from aops.core.config import AopsConfig
from aops.core.enums import Orientation, PaperPreset
from aops.core.errors import GeometryError
from aops.core.geometry import verify_splices
from aops.core.layout.strip import compose_strip_page
from aops.core.matrix import ModuleMatrix
from aops.core.project_io import config_fingerprint
from aops.core.stats import DerivedGeometry, derive
from aops.core.units import um_to_mm
from aops.render.zpl.backend import ZEBRA_RAW_PORT, ZplLabel, encode_label, rasterize
from aops.symbols.cache import SymbolCache


@dataclass(frozen=True, slots=True)
class ZplExportResult:
    paths: tuple[Path, ...]
    labels: tuple[ZplLabel, ...]
    total_bytes: int

    @property
    def piece_count(self) -> int:
        return len(self.paths)


def _piece_config(cfg: AopsConfig) -> AopsConfig:
    """The job repaginated onto printer-length virtual paper, one row a piece."""
    limit = cfg.output.continuous_max_length_mm
    if cfg.printer.max_label_length_mm > 0:
        limit = min(limit, cfg.printer.max_label_length_mm)
    if limit <= 0:
        raise GeometryError("The piece length limit must be positive.")
    paper = cfg.paper
    return dc.replace(
        cfg,
        paper=dc.replace(
            paper,
            preset=PaperPreset.CUSTOM,
            orientation=Orientation.LANDSCAPE,
            custom_width_mm=limit + paper.margin_left_mm + paper.margin_right_mm,
            custom_height_mm=50.0,
        ),
        output=dc.replace(cfg.output, tiled_pages=True, continuous=False,
                          rows_per_sheet=1),
    )


def _trim_trailing_white(image: Image.Image, dpi: int) -> Image.Image:
    """Cut the unused tail off a short last piece - media costs money.

    Only the right edge (the strip's far end) is trimmed, and never the
    left: every drawn coordinate keeps its position.
    """
    from PIL import ImageOps

    bbox = ImageOps.invert(image.convert("L")).getbbox()
    if bbox is None:
        return image
    pad = round(2.0 / 25.4 * dpi)
    right = min(image.size[0], bbox[2] + pad)
    return image.crop((0, 0, right, image.size[1]))


def export_zpl(
    cfg: AopsConfig,
    derived: DerivedGeometry,
    cache: SymbolCache,
    out_path: str | os.PathLike[str],
    *,
    cancel: Event | None = None,
) -> ZplExportResult:
    """Write the strip as one `.zpl` file per printer-sized piece.

    `out_path` names the first piece; multi-piece jobs get `_rollNN`
    suffixes exactly like the continuous PDF export.
    """
    piece_cfg = _piece_config(cfg)
    pieces = derive(piece_cfg, matrix_cols=derived.matrix_cols)

    violations = verify_splices(pieces.pages, pieces.cell)
    if violations:
        raise GeometryError(
            "Refusing to export: a piece boundary would cut a symbol.\n  "
            + "\n  ".join(violations[:5])
        )

    max_mm = cfg.printer.max_label_length_mm
    matrices: dict[str, ModuleMatrix] = {}
    for payload in dict.fromkeys(pieces.payloads):
        if cancel is not None and cancel.is_set():
            raise GeometryError("Export cancelled.")
        matrices[payload] = cache.get(cfg.symbol.symbology, payload)

    fingerprint = config_fingerprint(cfg)
    base = Path(out_path)
    if base.suffix.lower() != ".zpl":
        base = base.with_suffix(".zpl")

    paths: list[Path] = []
    labels: list[ZplLabel] = []
    # A page holding only leading or trailing white would print a label of
    # furniture and no codes - the installer's spare media does that job
    # for free.
    coded = [page for page in pieces.pages if page.cell_count > 0]
    total = len(coded)
    for page in coded:
        # Compose against paper exactly as long as this piece, so a short
        # last piece gets short furniture - header and footer rules span the
        # content width, and a 70 mm tail must not drag 990 mm of them.
        length_mm = um_to_mm(page.content_length_um)
        page_cfg = dc.replace(
            piece_cfg,
            paper=dc.replace(
                piece_cfg.paper,
                custom_width_mm=length_mm + piece_cfg.paper.margin_left_mm
                + piece_cfg.paper.margin_right_mm,
            ),
            # A short tail cannot hold the calibration bar; a clipped bar is
            # worse than none (it invites measuring a truncated length).
            output=dc.replace(
                piece_cfg.output,
                calibration_bar=piece_cfg.output.calibration_bar
                and length_mm >= cfg.printing.calibration_length_mm + 5.0,
            ),
        )
        lists = compose_strip_page(page, page_cfg, pieces, matrices, fingerprint)
        image = rasterize(lists.content, cfg.printer.dpi, cfg.printing.scale_factor)
        image = _trim_trailing_white(image, cfg.printer.dpi)
        label = encode_label(image)

        if max_mm > 0 and label.length_dots > max_mm / 25.4 * cfg.printer.dpi + 1:
            raise GeometryError(  # pragma: no cover - pagination caps the length
                f"A piece came out longer than the printer's {max_mm:.0f} mm limit."
            )

        path = (
            base.with_name(f"{base.stem}_roll{page.strip_page_number:02d}{base.suffix}")
            if total > 1
            else base
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(label.data, encoding="ascii")
        paths.append(path)
        labels.append(label)

    return ZplExportResult(
        paths=tuple(paths),
        labels=tuple(labels),
        total_bytes=sum(p.stat().st_size for p in paths),
    )


def send_zpl(
    data: str | bytes, host: str, port: int = ZEBRA_RAW_PORT, *, timeout: float = 10.0
) -> int:
    """Send one label to a printer's raw port (9100). Returns bytes sent.

    This is the whole protocol: Zebra's raw port takes ZPL bytes and prints
    them. No driver, no handshake, no status - print a proof and measure the
    calibration bar, because nothing here can tell you the media slipped.
    """
    payload = data.encode("ascii") if isinstance(data, str) else data
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(payload)
    return len(payload)
