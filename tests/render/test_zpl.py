"""Native ZPL output: the rasterizer, the encoder, the exporter, the wire.

THE PROPERTY THAT MATTERS
-------------------------
The ZPL path promises dot fidelity: the artwork the validator approved,
rendered at exactly one printer dot per grid dot, with nothing downstream
able to rescale it. So the tests here decode our own output - unpack the
^GFA hex back into a bitmap - and check the dots, rather than trusting the
encoder that produced them.
"""

from __future__ import annotations

import dataclasses as dc
import socketserver
import threading

import pytest
from PIL import Image

from aops.core.config import AopsConfig, DimensionConfig, PositionConfig
from aops.core.drawlist import DrawList, Line, Rect, Style, SymbolPrim
from aops.core.enums import ContinuousStrategy
from aops.core.errors import GeometryError
from aops.core.matrix import matrix_from_rows
from aops.core.rules import ALL_RULES
from aops.core.stats import derive
from aops.core.validation import run_rules
from aops.render.zpl.backend import encode_label, rasterize
from aops.render.zpl.export import export_zpl, send_zpl
from aops.symbols.cache import SymbolCache
from aops.symbols.registry import build_registry


def checker(cols: int, rows: int):
    """A tiny fake matrix with a known pattern: dark where (r+c) is even."""
    return matrix_from_rows(
        [[(r + c) % 2 == 0 for c in range(cols)] for r in range(rows)],
        symbology="test", payload="checker", quiet_modules=0,
    )


def unpack(label) -> Image.Image:
    """Decode our own ^GFA hex back into an image (x across head, y feed)."""
    hex_data = label.data.split(",\n", 1)[1].split("\n^FS", 1)[0]
    raw = bytes.fromhex(hex_data.replace("\n", ""))
    img = Image.frombytes(
        "1", (label.bytes_per_row * 8, label.length_dots),
        bytes(~b & 0xFF for b in raw),
    )
    return img.crop((0, 0, label.width_dots, label.length_dots))


# -- the rasterizer ---------------------------------------------------------


def test_a_whole_dot_module_lands_on_exactly_that_many_dots():
    """The dot-grid promise, kept to the pixel: a 10-module symbol sized to
    5 dots per module produces 5-pixel module runs, no cracks, no overlaps."""
    dpi = 203
    dot_mm = 25.4 / dpi
    size_mm = 50 * dot_mm  # 10 modules x 5 dots
    lists = DrawList(size_mm + 2, size_mm + 2,
                     (SymbolPrim(0.0, 0.0, size_mm, checker(10, 10)),))
    img = rasterize(lists, dpi)
    px = img.load()
    # Row 0 of the checker: dark, light, dark... in exact 5-dot runs.
    for x in range(50):
        expected = 0 if (x // 5) % 2 == 0 else 1
        assert px[x, 2] == expected, x


def test_scale_factor_stretches_the_dots_like_the_pdf_transform():
    lists = DrawList(100.0, 10.0, (Rect(0.0, 0.0, 100.0, 10.0,
                                        Style(stroke=None, fill=(0, 0, 0))),))
    plain = rasterize(lists, 203, 1.0)
    scaled = rasterize(lists, 203, 1.01)
    assert scaled.size[0] == round(plain.size[0] * 1.01)


def test_greys_print_black_on_a_one_bit_device():
    lists = DrawList(10.0, 10.0,
                     (Line(0.0, 5.0, 10.0, 5.0, Style(stroke=(0.75, 0.75, 0.75))),))
    img = rasterize(lists, 203)
    assert 0 in img.crop((0, 35, 80, 45)).getdata()


def test_dashed_lines_have_gaps():
    lists = DrawList(50.0, 4.0,
                     (Line(0.0, 2.0, 50.0, 2.0,
                           Style(stroke=(0, 0, 0), dash_mm=(2.0, 2.0))),))
    img = rasterize(lists, 203)
    row = [img.load()[x, 16] for x in range(img.size[0])]
    assert 0 in row and 1 in row  # ink and gaps both present


# -- the encoder ------------------------------------------------------------


def test_the_label_frames_and_measures_correctly():
    img = Image.new("1", (100, 40), 1)  # 100 dots long, 40 dots of band
    label = encode_label(img)
    # Rotated a quarter turn: band across the head, length down the feed.
    assert label.width_dots == 40
    assert label.length_dots == 100
    assert label.data.startswith("^XA")
    assert label.data.rstrip().endswith("^XZ")
    assert "^PW40" in label.data
    assert "^LL100" in label.data
    assert "^MNN" in label.data
    assert f"^GFA,{label.bytes_per_row * 100},{label.bytes_per_row * 100},{label.bytes_per_row}," in label.data


def test_the_hex_round_trips_to_the_same_dots_without_mirroring():
    """Decode our own output and walk back to the natural orientation. A
    rotation must restore the original exactly - a mirror here would print
    chirality-flipped symbols."""
    dpi = 203
    lists = DrawList(30.0, 6.0, (
        Rect(1.0, 1.0, 4.0, 4.0, Style(stroke=None, fill=(0, 0, 0))),
        SymbolPrim(10.0, 1.0, 4.0, checker(8, 8)),
    ))
    natural = rasterize(lists, dpi)
    label = encode_label(natural)
    restored = unpack(label).transpose(Image.Transpose.ROTATE_90)
    assert restored.size == natural.size
    # Pillow reports 1-bit pixels as 0/1 or 0/255 depending on the image's
    # provenance; the dots, not the representation, are the contract.
    assert [p != 0 for p in restored.getdata()] == [p != 0 for p in natural.getdata()]


def test_strip_start_prints_first():
    """The strip's x=0 end must be the first thing off the printer."""
    img = Image.new("1", (100, 10), 1)
    img.paste(0, (0, 0, 5, 10))  # ink only at the strip's start
    label = encode_label(img)
    decoded = unpack(label)
    top = decoded.crop((0, 0, label.width_dots, 5))
    bottom = decoded.crop((0, 95, label.width_dots, 100))
    assert 0 in top.getdata()
    assert 0 not in bottom.getdata()


# -- the exporter -----------------------------------------------------------


def job() -> AopsConfig:
    cfg = AopsConfig()
    return dc.replace(
        cfg,
        dimensions=DimensionConfig(pitch_mm=25.0, symbol_size_mm=10.0,
                                   strip_height_mm=20.0),
        position=PositionConfig(start_index=0, end_index=30),
        printer=dc.replace(cfg.printer, dpi=203),
    )


def export(cfg, tmp_path):
    cache = SymbolCache(build_registry(cfg.symbol))
    return export_zpl(cfg, derive(cfg), cache, tmp_path / "strip.zpl")


def test_pieces_split_at_cell_boundaries_within_the_printer_limit(tmp_path):
    """The paginator, not arithmetic, makes the pieces: 31 codes at 25 mm on
    a 400 mm printer is 15 cells behind the leader plus 16 more - two labels,
    each within the limit, every boundary on a cell edge in white. (The first
    draft split evenly like the PDF roll strategy, which can land a label
    edge mid-code.)"""
    cfg = dc.replace(
        job(),
        printer=dc.replace(job().printer, max_label_length_mm=400.0),
        output=dc.replace(job().output,
                          continuous_strategy=ContinuousStrategy.USER_UNIT),
    )
    result = export(cfg, tmp_path)
    assert result.piece_count == 2
    assert [p.name for p in result.paths] == ["strip_roll01.zpl", "strip_roll02.zpl"]
    for label in result.labels:
        assert label.length_dots <= round(400.0 / 25.4 * 203) + 1


def test_a_short_strip_is_one_label(tmp_path):
    cfg = dc.replace(job(), printer=dc.replace(job().printer,
                                               max_label_length_mm=990.0))
    result = export(cfg, tmp_path)
    assert result.piece_count == 1
    assert result.paths[0].name == "strip.zpl"
    text = result.paths[0].read_text(encoding="ascii")
    assert text.startswith("^XA")
    label = result.labels[0]
    # The strip runs down the feed; with the furniture stripped, the label's
    # width across the head is the bare band - narrow media, not a 4-inch
    # sheet of decoration.
    assert label.length_dots > label.width_dots
    band_dots = round(20.0 / 25.4 * 203)
    assert band_dots <= label.width_dots <= band_dots + round(6.0 / 25.4 * 203)


def test_a_label_is_codes_and_values_and_nothing_else():
    """The operator's requirement, verbatim: 'if it is a ZPL export, I just
    want the barcodes printed along with the value below'. No header, no
    ruler, no calibration bar, no outlines, no splice labels - every text on
    a piece is a code's own value, and the only geometry is the symbols."""
    from aops.core.drawlist import Line, Rect, SymbolPrim, Text
    from aops.core.layout.strip import compose_strip_page
    from aops.core.project_io import config_fingerprint
    from aops.render.zpl.export import _piece_config

    # Even a config with every furniture switch ON, and values OFF:
    cfg = job()
    cfg = dc.replace(
        cfg,
        printer=dc.replace(cfg.printer, max_label_length_mm=400.0),
        output=dc.replace(cfg.output, human_readable=False),
    )
    piece_cfg = _piece_config(cfg)
    pieces = derive(piece_cfg, matrix_cols=10)
    cache = SymbolCache(build_registry(cfg.symbol))
    matrices = {p: cache.get(cfg.symbol.symbology, p) for p in dict.fromkeys(pieces.payloads)}

    for page in pieces.pages:
        if page.cell_count == 0:
            continue
        lists = compose_strip_page(page, piece_cfg, pieces, matrices,
                                   config_fingerprint(cfg))
        texts = [i for i in lists.content.items if isinstance(i, Text)]
        symbols = [i for i in lists.content.items if isinstance(i, SymbolPrim)]
        assert symbols, "a piece must carry its codes"
        assert len(texts) == len(symbols)  # one value under every code
        assert all(t.text.isdigit() for t in texts), [t.text for t in texts]
        assert not [i for i in lists.content.items if isinstance(i, Line | Rect)]


def test_the_wire_carries_exactly_the_file(tmp_path):
    received = bytearray()
    done = threading.Event()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            received.extend(self.rfile.read())
            done.set()

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        payload = "^XA^PW8^LL1^XZ\n"
        sent = send_zpl(payload, "127.0.0.1", server.server_address[1])
        assert done.wait(5.0)
        thread.join(5.0)
    assert sent == len(payload)
    assert bytes(received) == payload.encode("ascii")


# -- the rule and the preset ------------------------------------------------


def test_oversized_pieces_warn_with_a_one_click_cap():
    cfg = dc.replace(job(), printer=dc.replace(job().printer,
                                               max_label_length_mm=400.0))
    report = run_rules(ALL_RULES, cfg, derive(cfg))
    finding = next(f for f in report.findings if f.rule_id == "PRN-012")
    assert finding.fix is not None and finding.fix.value == 400.0

    capped = dc.replace(cfg, output=dc.replace(cfg.output,
                                               continuous_max_length_mm=400.0))
    assert "PRN-012" not in {f.rule_id for f in
                             run_rules(ALL_RULES, capped, derive(capped)).findings}

    # No stated maximum, no opinion.
    assert "PRN-012" not in {f.rule_id for f in
                             run_rules(ALL_RULES, job(), derive(job())).findings}


def test_the_zd230_preset_sets_the_device_facts():
    from aops.core.presets import BUILT_IN_PRESETS
    from aops.core.presets import apply as apply_preset

    preset = next(p for p in BUILT_IN_PRESETS if "ZD230" in p.name)
    cfg = apply_preset(preset, AopsConfig())
    assert cfg.printer.dpi == 203
    assert cfg.printer.max_label_length_mm == 990.0
    assert cfg.output.continuous_max_length_mm == 990.0


def test_splice_violations_still_refuse_export(tmp_path):
    """A symbol leaving 0.05 mm of white at the cell edge cannot give a piece
    boundary its quiet zone. One piece would hide it (no boundaries); the
    400 mm printer limit forces a split, and the split must refuse."""
    cfg = dc.replace(
        job(),
        dimensions=dc.replace(job().dimensions, symbol_size_mm=24.9),
        printer=dc.replace(job().printer, max_label_length_mm=400.0),
    )
    cache = SymbolCache(build_registry(cfg.symbol))
    with pytest.raises(GeometryError):
        export_zpl(cfg, derive(cfg), cache, tmp_path / "bad.zpl")


# -- the CLI ----------------------------------------------------------------


def test_the_cli_writes_zpl_end_to_end(tmp_path, capsys):
    from aops import __version__
    from aops.cli import main
    from aops.core.project_io import dump_project

    project = tmp_path / "job.aops"
    project.write_text(dump_project(job(), app_version=__version__), encoding="utf-8")

    code = main(["zpl", "--project", str(project), "--out", str(tmp_path / "out")])
    assert code == 0
    pieces = sorted((tmp_path / "out").glob("*.zpl"))
    assert pieces
    assert pieces[0].read_text(encoding="ascii").startswith("^XA")
    assert "wrote" in capsys.readouterr().out


# -- die-cut sticker rolls --------------------------------------------------


def test_die_cut_stock_packs_one_sticker_per_label(tmp_path):
    """100 mm stickers at 25 mm pitch hold exactly 4 codes each - no leading
    blank (a sticker provides its own handling), cell boundaries landing on
    the die-cut edges, all in ONE batch file with gap sensing on."""
    cfg = dc.replace(job(), printer=dc.replace(job().printer,
                                               label_length_mm=100.0))
    result = export(cfg, tmp_path)

    assert result.piece_count == 1  # one batch file
    assert result.paths[0].name == "strip.zpl"
    assert len(result.labels) == 8  # 4*7 + 3 = 31 codes
    text = result.paths[0].read_text(encoding="ascii")
    assert text.count("^XA") == 8
    assert "^MNY" in text and "^MNN" not in text

    sticker_dots = round(100.0 / 25.4 * 203)
    for label in result.labels:
        assert label.length_dots <= sticker_dots + 1


def test_die_cut_stickers_start_with_a_code_not_a_blank():
    """The 20 mm lead-in is continuous-media handling white; on stickers it
    was dead space at the start of the run. The first placed segment of the
    first sticker must be a cell."""
    from aops.core.enums import SegmentKind
    from aops.render.zpl.export import _piece_config

    cfg = dc.replace(job(), printer=dc.replace(job().printer,
                                               label_length_mm=100.0))
    pieces = derive(_piece_config(cfg), matrix_cols=10)
    first = pieces.pages[0]
    assert first.placed[0].segment.kind is SegmentKind.CELL
    # And the continuous path keeps its lead untouched.
    continuous = derive(_piece_config(job()), matrix_cols=10)
    assert continuous.pages[0].placed[0].segment.kind is SegmentKind.LEAD


def test_continuous_media_still_tracks_as_continuous(tmp_path):
    result = export(job(), tmp_path)
    text = result.paths[0].read_text(encoding="ascii")
    assert "^MNN" in text and "^MNY" not in text


def test_sticker_length_that_divides_the_pitch_stays_quiet():
    cfg = dc.replace(job(), printer=dc.replace(job().printer,
                                               label_length_mm=100.0))
    ids = {f.rule_id for f in run_rules(ALL_RULES, cfg, derive(cfg)).findings}
    assert "PRN-013" not in ids


def test_sticker_length_with_dead_tail_gets_the_hint():
    """A 100 mm sticker at 15 mm pitch ends with 10 mm of dead label."""
    cfg = dc.replace(
        job(),
        dimensions=dc.replace(job().dimensions, pitch_mm=15.0,
                              symbol_size_mm=8.0),
        printer=dc.replace(job().printer, label_length_mm=100.0),
    )
    report = run_rules(ALL_RULES, cfg, derive(cfg))
    finding = next(f for f in report.findings if f.rule_id == "PRN-013")
    assert "10.0 mm" in finding.message
    assert "90" in finding.hint and "105" in finding.hint


def test_the_gap_is_default_until_measured():
    """0 means 'assume the 3 mm industry norm'; a typed value is the
    measurement. The effective property is what any consumer reasons with."""
    from aops.core.config import DEFAULT_LABEL_GAP_MM

    base = AopsConfig().printer
    assert base.label_gap_mm == 0.0
    assert base.effective_label_gap_mm == DEFAULT_LABEL_GAP_MM

    measured = dc.replace(base, label_gap_mm=4.2)
    assert measured.effective_label_gap_mm == 4.2
