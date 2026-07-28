"""Font-role resolution for the PDF backend.

Roles are resolved to ReportLab's built-in Type 1 fonts, which are guaranteed
present in every PDF viewer and RIP without embedding. For an engineering
document this is the right trade: Courier and Helvetica are unglamorous but
universally available, and nothing in a positioning strip needs a display face.
"""

from __future__ import annotations

from aops.core.enums import FontRole

#: FontRole -> ReportLab base-14 font name.
PDF_FONTS: dict[FontRole, str] = {
    FontRole.MONO: "Courier",
    FontRole.MONO_BOLD: "Courier-Bold",
    FontRole.SANS: "Helvetica",
    FontRole.SANS_BOLD: "Helvetica-Bold",
}


def pdf_font(role: FontRole) -> str:
    return PDF_FONTS.get(role, "Courier")
