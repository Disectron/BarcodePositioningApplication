"""PDF structure, /UserUnit handling and the export-time safety checks."""

from __future__ import annotations

import dataclasses as dc
import re

import pytest

from aops.core.config import AopsConfig, DimensionConfig, PositionConfig, ProjectConfig
from aops.core.enums import ContinuousStrategy, VerifyMode
from aops.core.stats import derive, user_unit_for
from aops.core.units import PDF_MAX_PT, mm_to_pt
from aops.render.pdf.export import export_continuous, export_tiled
from aops.symbols.cache import SymbolCache
from aops.symbols.datamatrix import DataMatrixEncoder
from aops.symbols.registry import build_registry


@pytest.fixture(scope="module")
def cache() -> SymbolCache:
    if not DataMatrixEncoder().available:
        pytest.skip("libdmtx unavailable")
    return SymbolCache(build_registry())


@pytest.fixture
def project_cfg() -> AopsConfig:
    base = AopsConfig()
    return dc.replace(
        base,
        project=ProjectConfig(machine="GANTRY-01", project="LINE 4", strip_id="AX1-POS-001",
                              revision="B", engineer="Test"),
        output=dc.replace(base.output, verify_mode=VerifyMode.SAMPLE, verify_sample_count=6),
    )


# -- UserUnit ---------------------------------------------------------------


def test_user_unit_calculation():
    assert user_unit_for(1000.0, 100.0) == 1.0
    assert user_unit_for(mm_to_pt(10565.0), mm_to_pt(80.0)) == pytest.approx(2.08)


def test_continuous_declares_user_unit_when_oversized(project_cfg, cache, tmp_path):
    cfg = dc.replace(project_cfg, output=dc.replace(project_cfg.output, continuous=True))
    derived = derive(cfg)
    assert derived.continuous.over_limit

    result = export_continuous(cfg, derived, cache, tmp_path / "cont.pdf")
    data = result.path.read_bytes()

    match = re.search(rb"/UserUnit\s*([0-9.]+)", data)
    assert match, "/UserUnit was not emitted for an oversized page"
    assert float(match.group(1)) == pytest.approx(2.08)
    assert data.startswith(b"%PDF-1.6"), "UserUnit requires PDF 1.6 or later"

    box = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)", data)
    assert box
    width_pt = float(box.group(1))
    assert width_pt <= PDF_MAX_PT, "MediaBox must stay inside the conformant limit"
    # The page still measures true size once UserUnit is applied.
    assert width_pt * 2.08 == pytest.approx(mm_to_pt(derived.total_length_mm), rel=1e-3)


def test_short_strip_omits_user_unit(project_cfg, cache, tmp_path):
    cfg = dc.replace(
        project_cfg,
        position=PositionConfig(start_index=0, end_index=20),
        output=dc.replace(project_cfg.output, continuous=True),
    )
    derived = derive(cfg)
    assert not derived.continuous.over_limit
    result = export_continuous(cfg, derived, cache, tmp_path / "short.pdf")
    assert b"/UserUnit" not in result.path.read_bytes()


def test_user_unit_patch_is_fully_reverted(project_cfg, cache, tmp_path):
    """The scoped monkeypatch must not leak into later PDFs."""
    from reportlab.pdfbase import pdfdoc

    original_format = pdfdoc.PDFPage.format
    original_nodefault = list(pdfdoc.PDFPage.__NoDefault__)

    cfg = dc.replace(project_cfg, output=dc.replace(project_cfg.output, continuous=True))
    export_continuous(cfg, derive(cfg), cache, tmp_path / "leak.pdf")

    assert pdfdoc.PDFPage.format is original_format
    assert list(pdfdoc.PDFPage.__NoDefault__) == original_nodefault


def test_split_roll_produces_multiple_conformant_files(project_cfg, cache, tmp_path):
    cfg = dc.replace(
        project_cfg,
        output=dc.replace(
            project_cfg.output,
            continuous=True,
            continuous_strategy=ContinuousStrategy.SPLIT_ROLL,
            continuous_max_length_mm=3000.0,
        ),
    )
    derived = derive(cfg)
    assert derived.continuous.roll_count == 4
    result = export_continuous(cfg, derived, cache, tmp_path / "roll.pdf")
    assert len(result.paths) == 4
    for path in result.paths:
        assert b"/UserUnit" not in path.read_bytes()


# -- tiled export -----------------------------------------------------------


def test_tiled_page_count_and_content(project_cfg, cache, tmp_path):
    derived = derive(project_cfg)
    result = export_tiled(project_cfg, derived, cache, tmp_path / "tiles.pdf")

    # Guide pages plus one page per strip sheet.
    assert result.page_count >= len(derived.pages) + 1
    assert result.total_bytes > 0
    assert result.verified_count > 0, "sampling mode should verify some symbols"

    data = result.path.read_bytes()
    assert b"AOPS" in data


def test_export_refuses_when_pagination_would_cut_a_symbol(project_cfg, cache, tmp_path, monkeypatch):
    """The export-time splice re-check is a real gate, not decoration."""
    from aops.core.errors import GeometryError
    from aops.render.pdf import export as export_mod

    monkeypatch.setattr(
        export_mod, "verify_splices", lambda pages, cell: ("synthetic violation",)
    )
    derived = derive(project_cfg)
    with pytest.raises(GeometryError, match="would cut a symbol"):
        export_tiled(project_cfg, derived, cache, tmp_path / "bad.pdf")


def test_estimated_size_is_in_the_right_ballpark(project_cfg, cache, tmp_path):
    derived = derive(project_cfg)
    result = export_tiled(project_cfg, derived, cache, tmp_path / "size.pdf")
    estimate = derived.estimated_pdf_bytes()
    assert 0.25 <= result.total_bytes / estimate <= 4.0, (
        f"estimate {estimate} vs actual {result.total_bytes}"
    )


def test_verification_off_skips_decoding(project_cfg, cache, tmp_path):
    cfg = dc.replace(project_cfg, output=dc.replace(project_cfg.output, verify_mode=VerifyMode.OFF))
    result = export_tiled(cfg, derive(cfg), cache, tmp_path / "noverify.pdf")
    assert result.verified_count == 0


def test_export_handles_a_single_code(cache, tmp_path):
    cfg = dc.replace(
        AopsConfig(),
        position=PositionConfig(start_index=0, end_index=0),
        dimensions=DimensionConfig(),
    )
    derived = derive(cfg)
    result = export_tiled(cfg, derived, cache, tmp_path / "one.pdf")
    assert result.page_count >= 2
