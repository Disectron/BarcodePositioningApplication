"""Reusable configuration presets.

A project file answers "which strip is this?". A preset answers "how do we
build strips here?" - the geometry, the substrate, the printer, the reader.
The second is what an engineer repeats on every job; the first is what changes
every time.

That distinction is the whole design. **A preset deliberately does not carry
the identity of a strip.** If it did, applying "our standard 25 mm polyester
setup" to a new job would also stamp it with another machine's name, another
axis's length and someone else's revision letter - and because every change
here is applied live, the mistake would be invisible until it reached a printed
sheet. `PER_STRIP_FIELDS` lists exactly what is held back, and the UI shows it,
so applying a preset can never quietly rewrite what strip you are working on.

Stored as JSON for the same reasons project files are: an engineer can read
one, diff one, and commit one next to the PLC source.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import Any, Final, get_type_hints

from aops.core.config import CONFIG_SECTIONS, AopsConfig
from aops.core.enums import (
    ContinuousStrategy,
    Media,
    PaperPreset,
    PrintMethod,
    Ribbon,
)
from aops.core.errors import ProjectFileError
from aops.core.project_io import decode_value, encode_value

PRESET_FILE_SUFFIX: Final[str] = ".aopspreset"
PRESET_FORMAT_TAG: Final[str] = "aops-preset"
PRESET_SCHEMA_VERSION: Final[int] = 1

#: Fields that describe *this* strip rather than how strips are made here.
#: Held back when capturing, and never written when applying.
#:
#: `position.increment`, `pitch_mode`, `direction` and `datum` are absent on
#: purpose - they are house convention, not per-strip facts, so a preset should
#: carry them. Only the range, the origin and the identifying text are excluded.
PER_STRIP_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "position.start_index",
        "position.end_index",
        "position.origin_mm",
        "project.machine",
        "project.project",
        "project.strip_id",
        "project.revision",
        "project.comments",
    }
)


@dataclass(frozen=True, slots=True)
class Preset:
    """A named, reusable subset of a configuration."""

    name: str
    description: str = ""
    #: section name -> {field: JSON-safe value}
    values: tuple[tuple[str, tuple[tuple[str, Any], ...]], ...] = ()

    @property
    def field_count(self) -> int:
        return sum(len(fields) for _section, fields in self.values)

    def sections(self) -> tuple[str, ...]:
        return tuple(section for section, _fields in self.values)


def capture(cfg: AopsConfig, name: str, description: str = "") -> Preset:
    """Take everything from `cfg` except the per-strip identity."""
    captured: list[tuple[str, tuple[tuple[str, Any], ...]]] = []

    for section_name in CONFIG_SECTIONS:
        section = getattr(cfg, section_name)
        fields: list[tuple[str, Any]] = []
        for f in dataclasses.fields(section):
            path = f"{section_name}.{f.name}"
            if path in PER_STRIP_FIELDS:
                continue
            fields.append((f.name, encode_value(getattr(section, f.name))))
        if fields:
            captured.append((section_name, tuple(fields)))

    return Preset(name=name, description=description, values=tuple(captured))


def apply(preset: Preset, cfg: AopsConfig) -> AopsConfig:
    """Return `cfg` with the preset's values written over it.

    Unknown sections and fields are skipped rather than raising: a preset
    written by a newer build should still apply what this one understands
    instead of refusing outright.
    """
    updated = cfg

    for section_name, fields in preset.values:
        section = getattr(updated, section_name, None)
        if section is None or not dataclasses.is_dataclass(section):
            continue

        hints = get_type_hints(type(section))
        known = {f.name for f in dataclasses.fields(section)}
        changes: dict[str, Any] = {}
        for field_name, raw in fields:
            path = f"{section_name}.{field_name}"
            if field_name not in known or path in PER_STRIP_FIELDS:
                continue
            changes[field_name] = decode_value(raw, hints[field_name])

        if changes:
            updated = dataclasses.replace(
                updated, **{section_name: dataclasses.replace(section, **changes)}
            )

    return updated


def dump_preset(preset: Preset, *, app_version: str) -> str:
    """Serialise a preset to JSON text."""
    envelope = {
        "format": PRESET_FORMAT_TAG,
        "schema_version": PRESET_SCHEMA_VERSION,
        "app_version": app_version,
        "name": preset.name,
        "description": preset.description,
        "values": {section: dict(fields) for section, fields in preset.values},
    }
    return json.dumps(envelope, indent=2, sort_keys=True) + "\n"


def load_preset(text: str) -> Preset:
    """Parse preset JSON text. Raises `ProjectFileError` on malformed input."""
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectFileError(f"Not valid JSON: {exc}") from exc

    if not isinstance(envelope, dict):
        raise ProjectFileError("Preset file must contain a JSON object.")
    if envelope.get("format") != PRESET_FORMAT_TAG:
        raise ProjectFileError(
            f"Not an AOPS preset (expected format {PRESET_FORMAT_TAG!r}, "
            f"found {envelope.get('format')!r})."
        )

    version = envelope.get("schema_version")
    if not isinstance(version, int):
        raise ProjectFileError("Preset file has no valid 'schema_version'.")
    if version > PRESET_SCHEMA_VERSION:
        raise ProjectFileError(
            f"This preset was written by AOPS {envelope.get('app_version', '(unknown)')} "
            f"using schema {version}; this build supports {PRESET_SCHEMA_VERSION}."
        )

    raw_values = envelope.get("values")
    if not isinstance(raw_values, dict):
        raise ProjectFileError("Preset file has no 'values' object.")

    values = tuple(
        (section, tuple(sorted(fields.items())))
        for section, fields in sorted(raw_values.items())
        if isinstance(fields, dict)
    )
    return Preset(
        name=str(envelope.get("name") or "Unnamed"),
        description=str(envelope.get("description") or ""),
        values=values,
    )


def _built_in(name: str, description: str, **sections: dict[str, Any]) -> Preset:
    """Build a partial preset from literal values, encoded like any other."""
    return Preset(
        name=name,
        description=description,
        values=tuple(
            (section, tuple((k, encode_value(v)) for k, v in sorted(fields.items())))
            for section, fields in sorted(sections.items())
        ),
    )


#: Shipped starting points. Unlike a captured preset these are partial - each
#: sets only the fields that define it, so applying one changes nothing else.
BUILT_IN_PRESETS: Final[tuple[Preset, ...]] = (
    _built_in(
        "Label roll, 4 inch continuous",
        "Thermal transfer on continuous polyester with a resin ribbon, printed "
        "in one piece. No sheets to cut, align or splice.",
        paper={
            "preset": PaperPreset.ROLL_4IN,
            "margin_left_mm": 3.0,
            "margin_right_mm": 3.0,
            "margin_top_mm": 3.0,
            "margin_bottom_mm": 3.0,
        },
        output={
            "tiled_pages": False,
            "continuous": True,
            "continuous_strategy": ContinuousStrategy.USER_UNIT,
        },
        media={
            "media": Media.POLYESTER,
            "method": PrintMethod.THERMAL_TRANSFER,
            "ribbon": Ribbon.RESIN,
            "adhesive_backed": True,
        },
        # 203 dpi is 8 dots/mm, which lands a 1.000 mm module on exactly 8
        # whole dots. Label printers also print the full roll width, so there
        # is no unprintable border to allow for.
        printer={"dpi": 203, "unprintable_margin_mm": 0.0},
    ),
    _built_in(
        "A4 sheets, commissioning set",
        "Tiled A4 with the full engineering furniture: calibration bar, ruler, "
        "marks and the installation guide.",
        paper={"preset": PaperPreset.A4},
        output={
            "tiled_pages": True,
            "continuous": False,
            "calibration_bar": True,
            "engineering_ruler": True,
            "human_readable": True,
            "page_header_footer": True,
            "instruction_page": True,
        },
        printing={"registration_marks": True, "cut_marks": True, "alignment_arrows": True},
    ),
    _built_in(
        "Fine pitch, 12.5 mm",
        "Half the usual spacing for twice the position resolution. Encodes "
        "tenths of a millimetre, because 12.5 mm steps cannot be represented "
        "in whole millimetres.",
        dimensions={"pitch_mm": 12.5, "symbol_size_mm": 8.0, "quiet_zone_mm": 1.0},
        payload={"unit_scale": 10, "digits": 6},
    ),
)
