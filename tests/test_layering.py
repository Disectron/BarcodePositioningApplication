"""Enforces the inward-only dependency rule by scanning imports.

    ui -> controller -> render -> symbols -> core

`core` must remain importable with no Qt, no ReportLab and no imaging library
present. That is not architectural purity for its own sake: it is what makes the
geometry engine testable in isolation and what keeps a headless CI run cheap.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "aops"

FORBIDDEN: dict[str, tuple[str, ...]] = {
    "core": ("PySide6", "reportlab", "qrcode", "pylibdmtx", "PIL"),
    "symbols": ("PySide6", "reportlab"),
    "render.pdf": ("PySide6",),
    "render.qt": ("reportlab", "pylibdmtx"),
    "ui": ("reportlab", "pylibdmtx", "qrcode"),
    "resources": ("PySide6", "reportlab", "qrcode", "pylibdmtx", "PIL"),
}


def _module_key(path: pathlib.Path) -> str:
    rel = path.relative_to(SRC).with_suffix("")
    parts = rel.parts
    return ".".join(parts[:-1]) if parts[-1] == "__init__" else ".".join(parts)


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


ALL_MODULES = sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("path", ALL_MODULES, ids=lambda p: _module_key(p))
def test_module_respects_layering(path: pathlib.Path):
    key = _module_key(path)
    imports = _imports(path)
    for prefix, banned in FORBIDDEN.items():
        if key == prefix or key.startswith(prefix + "."):
            offending = imports & set(banned)
            assert not offending, (
                f"{key} imports {sorted(offending)}, which the {prefix} layer must not depend on"
            )


def test_core_imports_with_no_third_party_libraries(monkeypatch):
    """The pure domain must not need Qt, ReportLab or Pillow to import."""
    import builtins

    blocked = {"PySide6", "reportlab", "qrcode", "pylibdmtx", "PIL"}
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in blocked:
            raise ImportError(f"{name} is blocked by this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)

    for module in (
        "aops.core.units",
        "aops.core.cell",
        "aops.core.geometry",
        "aops.core.positions",
        "aops.core.payload",
        "aops.core.stats",
        "aops.core.rules",
        "aops.core.layout.strip",
        "aops.core.layout.guide",
    ):
        real_import(module)
