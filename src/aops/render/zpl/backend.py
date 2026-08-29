"""Rasterizing `Painter` and ZPL encoding for Zebra label printers.

A Zebra printer is a 1-bit device at a fixed resolution, which makes the
faithful export a *bitmap*, not a description: every design millimetre maps to
an exact printer dot, the same dot grid the whole geometry was designed on.
The painter renders the shared `DrawList` - the identical layout the preview
and the PDF walk - into a Pillow 1-bit image at the printer's native dpi, and
the encoder wraps that image in a minimal ZPL label (`^GFA` graphic field).

Why a bitmap and not ZPL's own barcode commands (^BX): the printer's encoder
would lay out its own matrix, outside the splice guarantee, the dot-grid
proof and the decode verification. The bitmap is the artwork AOPS proved,
dot for dot.

Colour collapses to ink: this is a monochrome device, so anything with a
stroke or fill prints black. The grey cut lines exist to be faint on an
office proof; on a label they simply print.

Printer calibration (`printing.scale_factor`) multiplies the geometry here
exactly as the PDF emit does, so the measure-the-bar loop corrects a Zebra
the same way it corrects a laser.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from aops.core.drawlist import DrawList, Line, PolyLine, Rect, SymbolPrim, Text, render
from aops.core.enums import Anchor

#: Raw-print TCP port every Zebra listens on.
ZEBRA_RAW_PORT: int = 9100

_PIL_ANCHOR = {
    Anchor.BASELINE_LEFT: "ls",
    Anchor.BASELINE_CENTRE: "ms",
    Anchor.BASELINE_RIGHT: "rs",
}


class RasterPainter:
    """Draws a `DrawList` into a 1-bit image at `dpi`, dot for dot.

    `scale` is the printer-calibration factor; it multiplies every coordinate
    exactly as the PDF backend's canvas transform does.
    """

    def __init__(self, dpi: int, scale: float = 1.0) -> None:
        if dpi <= 0:
            raise ValueError(f"dpi must be positive (got {dpi})")
        self._k = dpi / 25.4 * scale
        self._fonts: dict[float, ImageFont.ImageFont | ImageFont.FreeTypeFont] = {}
        self.image: Image.Image | None = None
        self._draw: ImageDraw.ImageDraw | None = None

    # -- helpers ------------------------------------------------------------

    def _px(self, mm: float) -> int:
        return round(mm * self._k)

    def _pxf(self, mm: float) -> float:
        return mm * self._k

    def _font(self, size_pt: float):
        # A point is 1/72 inch; _k is dots per design millimetre, so
        # px = pt / 72 inch * 25.4 mm/inch * k dots/mm.
        size_px = size_pt / 72.0 * 25.4 * self._k
        key = round(size_px, 1)
        if key not in self._fonts:
            self._fonts[key] = ImageFont.load_default(size=max(6, round(size_px)))
        return self._fonts[key]

    def _width_px(self, style) -> int:
        return max(1, round(self._pxf(style.line_width_mm)))

    # -- Painter protocol ---------------------------------------------------

    def begin(self, width_mm: float, height_mm: float) -> None:
        w = max(1, self._px(width_mm))
        h = max(1, self._px(height_mm))
        self.image = Image.new("1", (w, h), 1)  # 1 = white
        self._draw = ImageDraw.Draw(self.image)

    def end(self) -> None:
        pass

    def rect(self, prim: Rect) -> None:
        d = self._draw
        x0, y0 = self._px(prim.x), self._px(prim.y)
        x1, y1 = self._px(prim.x + prim.w), self._px(prim.y + prim.h)
        if prim.style.fill is not None:
            d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=0)
        if prim.style.stroke is not None:
            d.rectangle([x0, y0, max(x0, x1 - 1), max(y0, y1 - 1)],
                        outline=0, width=self._width_px(prim.style))

    def line(self, prim: Line) -> None:
        if prim.style.stroke is None:
            return
        w = self._width_px(prim.style)
        p1 = (self._px(prim.x1), self._px(prim.y1))
        p2 = (self._px(prim.x2), self._px(prim.y2))
        if not prim.style.dash_mm:
            self._draw.line([p1, p2], fill=0, width=w)
            return
        # Dashes, drawn segment by segment along the line.
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length == 0:
            return
        ux, uy = dx / length, dy / length
        pattern = [max(1.0, self._pxf(d)) for d in prim.style.dash_mm]
        pos, i, on = 0.0, 0, True
        while pos < length:
            seg = min(pattern[i % len(pattern)], length - pos)
            if on:
                self._draw.line(
                    [(round(p1[0] + ux * pos), round(p1[1] + uy * pos)),
                     (round(p1[0] + ux * (pos + seg)), round(p1[1] + uy * (pos + seg)))],
                    fill=0, width=w,
                )
            pos += seg
            i += 1
            on = not on

    def polyline(self, prim: PolyLine) -> None:
        if len(prim.pts) < 2:
            return
        pts = [(self._px(x), self._px(y)) for x, y in prim.pts]
        if prim.close and prim.style.fill is not None:
            self._draw.polygon(pts, fill=0)
        if prim.close:
            pts = [*pts, pts[0]]
        if prim.style.stroke is not None:
            self._draw.line(pts, fill=0, width=self._width_px(prim.style))

    def text(self, prim: Text) -> None:
        # Rotated text is unused by the strip layouts; if it ever appears it
        # is drawn unrotated rather than silently dropped.
        self._draw.text(
            (self._px(prim.x), self._px(prim.y)),
            prim.text,
            font=self._font(prim.style.size_pt),
            fill=0,
            anchor=_PIL_ANCHOR.get(prim.anchor, "ls"),
        )

    def symbol(self, prim: SymbolPrim) -> None:
        """Modules as exact dot rectangles.

        Edges come from one rounded cumulative ladder, so adjacent modules
        neither crack nor overlap - and when the symbol is a whole number of
        dots per module (the solver's guarantee), every module lands on
        exactly that many dots.
        """
        m = prim.matrix
        if m.cols == 0 or m.rows == 0:
            return
        x0, y0 = self._pxf(prim.x), self._pxf(prim.y)
        size = self._pxf(prim.size_mm)
        xs = [round(x0 + size * i / m.cols) for i in range(m.cols + 1)]
        ys = [round(y0 + size * i / m.rows) for i in range(m.rows + 1)]
        d = self._draw
        for r in range(m.rows):
            for c in range(m.cols):
                if m.dark(r, c):
                    d.rectangle([xs[c], ys[r], xs[c + 1] - 1, ys[r + 1] - 1], fill=0)


@dataclass(frozen=True, slots=True)
class ZplLabel:
    """One encoded label and its physical description."""

    data: str
    width_dots: int  #: across the print head
    length_dots: int  #: along the feed direction

    @property
    def bytes_per_row(self) -> int:
        return (self.width_dots + 7) // 8


def rasterize(lists: DrawList, dpi: int, scale: float = 1.0) -> Image.Image:
    """Render a content draw list to a 1-bit image at printer resolution."""
    painter = RasterPainter(dpi, scale)
    render(lists, painter)
    assert painter.image is not None
    return painter.image


def encode_label(strip_image: Image.Image, *, gap_sensing: bool = False) -> ZplLabel:
    """Wrap a natural-orientation strip image (x = strip axis) in ZPL.

    ZPL's x runs across the print head and y along the media feed, and the
    strip prints lengthwise down the feed - so the image is rotated a quarter
    turn (a rotation, never a mirror: matrix symbols are chirality-sensitive).
    After ROTATE_270 the strip's start is the first thing off the printer.

    `gap_sensing` selects the media tracking mode: continuous media (^MNN,
    the default) is positioned by feed alone; die-cut stickers (^MNY) are
    registered by the printer's gap sensor, which finds each label's leading
    edge through the liner gap - so every sticker starts at a die-cut edge
    regardless of how far the previous one fed.

    The graphic field is plain uppercase hex: bigger than Zebra's compressed
    forms but deterministic, diffable and accepted by every firmware.
    """
    img = strip_image.transpose(Image.Transpose.ROTATE_270)
    width_dots, length_dots = img.size

    # PIL mode "1" packs rows MSB-first and byte-padded - exactly ZPL's
    # layout, except PIL says 1 for white and ZPL says 1 for ink.
    raw = bytes(~b & 0xFF for b in img.tobytes())
    per_row = (width_dots + 7) // 8
    total = per_row * length_dots
    hex_rows = "\n".join(
        raw[i * per_row:(i + 1) * per_row].hex().upper() for i in range(length_dots)
    )

    data = (
        "^XA\n"
        f"^PW{width_dots}\n"
        f"^LL{length_dots}\n"
        "^LH0,0\n"
        f"{'^MNY' if gap_sensing else '^MNN'}\n"
        f"^FO0,0^GFA,{total},{total},{per_row},\n{hex_rows}\n^FS\n"
        "^XZ\n"
    )
    return ZplLabel(data=data, width_dots=width_dots, length_dots=length_dots)
