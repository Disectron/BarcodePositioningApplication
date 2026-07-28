"""Font-role resolution for the Qt backend."""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase

from aops.core.enums import FontRole

#: Preference order per role. The first family actually installed wins.
_FAMILIES: dict[FontRole, tuple[str, ...]] = {
    FontRole.MONO: ("Consolas", "DejaVu Sans Mono", "Liberation Mono", "Courier New", "monospace"),
    FontRole.MONO_BOLD: ("Consolas", "DejaVu Sans Mono", "Liberation Mono", "Courier New", "monospace"),
    FontRole.SANS: ("Segoe UI", "DejaVu Sans", "Liberation Sans", "Arial", "sans-serif"),
    FontRole.SANS_BOLD: ("Segoe UI", "DejaVu Sans", "Liberation Sans", "Arial", "sans-serif"),
}

_resolved: dict[FontRole, str] = {}


def _family_for(role: FontRole) -> str:
    cached = _resolved.get(role)
    if cached is not None:
        return cached
    available = set(QFontDatabase.families())
    for candidate in _FAMILIES[role]:
        if candidate in available:
            _resolved[role] = candidate
            return candidate
    fallback = _FAMILIES[role][-1]
    _resolved[role] = fallback
    return fallback


def qt_font(role: FontRole, size_pt: float) -> QFont:
    font = QFont(_family_for(role))
    font.setPointSizeF(size_pt)
    if role in (FontRole.MONO_BOLD, FontRole.SANS_BOLD):
        font.setBold(True)
    if role in (FontRole.MONO, FontRole.MONO_BOLD):
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
    return font


def ui_font(size_pt: float = 9.0, *, mono: bool = False, bold: bool = False) -> QFont:
    """Font for chrome rather than for drawn output."""
    role = (FontRole.MONO_BOLD if bold else FontRole.MONO) if mono else (
        FontRole.SANS_BOLD if bold else FontRole.SANS
    )
    return qt_font(role, size_pt)
