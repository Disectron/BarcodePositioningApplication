"""Print styles - presets over the page-furniture switches.

The switches themselves stay the single source of truth. A style is derived
from them rather than stored alongside them, so the two can never disagree and
no project-file migration is needed: an older file simply reads as whatever
style its switches already describe.

Selecting a style writes the switches; changing a switch by hand moves the
configuration to CUSTOM on its own, with nothing to keep in sync.
"""

from __future__ import annotations

from dataclasses import replace

from aops.core.config import AopsConfig
from aops.core.enums import PrintStyle

#: Switches a style controls, by config section. Anything absent is left alone,
#: which is why cut_line_across_strip (off by default, and hostile to a scanner
#: whichever style is chosen) is not listed.
STYLE_FLAGS: dict[PrintStyle, dict[str, dict[str, bool]]] = {
    PrintStyle.PLAIN: {
        "output": {
            "instruction_page": False,
            "calibration_bar": False,
            "engineering_ruler": False,
            "human_readable": False,
            "page_header_footer": False,
        },
        "printing": {
            "registration_marks": False,
            "cut_marks": False,
            "alignment_arrows": False,
            "splice_labels": False,
        },
    },
    PrintStyle.LABELLED: {
        "output": {
            "instruction_page": False,
            "calibration_bar": False,
            "engineering_ruler": False,
            "human_readable": True,
            "page_header_footer": False,
        },
        "printing": {
            "registration_marks": False,
            "cut_marks": False,
            "alignment_arrows": False,
            "splice_labels": True,
        },
    },
    PrintStyle.ENGINEERING: {
        "output": {
            "instruction_page": True,
            "calibration_bar": True,
            "engineering_ruler": True,
            "human_readable": True,
            "page_header_footer": True,
        },
        "printing": {
            "registration_marks": True,
            "cut_marks": True,
            "alignment_arrows": True,
            "splice_labels": True,
        },
    },
}

#: Order matters only for reporting; the presets are mutually exclusive.
PRESET_STYLES: tuple[PrintStyle, ...] = (
    PrintStyle.PLAIN,
    PrintStyle.LABELLED,
    PrintStyle.ENGINEERING,
)


def apply_style(cfg: AopsConfig, style: PrintStyle) -> AopsConfig:
    """Return `cfg` with every switch the style controls set accordingly.

    CUSTOM is not a preset and changes nothing - it is what a configuration
    reports when it matches none of the others.
    """
    flags = STYLE_FLAGS.get(style)
    if flags is None:
        return cfg

    updated = cfg
    for section_name, changes in flags.items():
        section = getattr(updated, section_name)
        updated = replace(updated, **{section_name: replace(section, **changes)})
    return updated


def matches_style(cfg: AopsConfig, style: PrintStyle) -> bool:
    """True when every switch the style controls already holds its preset value."""
    flags = STYLE_FLAGS.get(style)
    if flags is None:
        return False
    return all(
        getattr(getattr(cfg, section_name), field) == value
        for section_name, changes in flags.items()
        for field, value in changes.items()
    )


def detect_style(cfg: AopsConfig) -> PrintStyle:
    """Which style the current switches describe, or CUSTOM."""
    for style in PRESET_STYLES:
        if matches_style(cfg, style):
            return style
    return PrintStyle.CUSTOM
