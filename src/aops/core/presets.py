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
    #: Optional menu grouping. Presets sharing a group get their own submenu,
    #: which keeps a family like the code sizes from burying everything else.
    group: str = ""

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
        "group": preset.group,
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
        group=str(envelope.get("group") or ""),
    )


def _built_in(
    name: str, description: str, *, group: str = "", **sections: dict[str, Any]
) -> Preset:
    """Build a partial preset from literal values, encoded like any other."""
    return Preset(
        name=name,
        description=description,
        group=group,
        values=tuple(
            (section, tuple((k, encode_value(v)) for k, v in sorted(fields.items())))
            for section, fields in sorted(sections.items())
        ),
    )


#: Menu group holding the code-size family.
SIZE_GROUP: Final[str] = "Code size"

#: (symbol, pitch, strip height) in mm for each shipped code size.
#:
#: Symbol size alone is not a usable preset. Enlarging the code enlarges its
#: modules, so the quiet zone must grow with it (one module of a 10x10 matrix,
#: which a six-digit payload produces); the pitch must clear symbol plus both
#: quiet zones with cutting tolerance left over; and the strip band has to be
#: tall enough to hold the code and its quiet zones. Change one and the other
#: three follow, which is exactly the coupling that makes this worth shipping
#: as presets rather than leaving to the user.
#:
#: Pitches are rounded to whole 5 mm steps: position is index x pitch, and a
#: controls engineer reading 0, 45, 90 off a strip has an easier time than one
#: reading 0, 42, 84.
_SIZE_TABLE_MM: Final[tuple[tuple[float, float, float], ...]] = (
    (20.0, 30.0, 40.0),
    (25.0, 40.0, 45.0),
    (30.0, 45.0, 50.0),
    (35.0, 50.0, 55.0),
    (40.0, 55.0, 60.0),
    (45.0, 60.0, 65.0),
    (50.0, 70.0, 70.0),
)

#: Modules across a Data Matrix carrying a six-digit payload.
_MATRIX_COLS: Final[int] = 10


def _size_preset(symbol_mm: float, pitch_mm: float, height_mm: float) -> Preset:
    """One code-size preset, with its consequences computed rather than typed.

    The description states what the size costs and buys - module size, position
    resolution, reader window - derived from the same numbers that go into the
    preset, so the text cannot drift away from what it describes.
    """
    quiet_mm = symbol_mm / _MATRIX_COLS
    module_mm = symbol_mm / _MATRIX_COLS
    fov_mm = pitch_mm + symbol_mm

    return _built_in(
        f"{symbol_mm:.0f} x {symbol_mm:.0f} mm code",
        f"{symbol_mm:.0f} mm code on a {pitch_mm:.0f} mm spacing, in a "
        f"{height_mm:.0f} mm band. Modules are {module_mm:.1f} mm, so it reads "
        f"from further away and survives more damage - but position resolves "
        f"only to {pitch_mm:.0f} mm, and the reader needs a {fov_mm:.0f} mm "
        f"window to never lose it.",
        group=SIZE_GROUP,
        dimensions={
            "symbol_size_mm": symbol_mm,
            "pitch_mm": pitch_mm,
            "strip_height_mm": height_mm,
            "quiet_zone_mm": quiet_mm,
        },
    )


#: One preset per code size from 20 x 20 mm to 50 x 50 mm.
SIZE_PRESETS: Final[tuple[Preset, ...]] = tuple(
    _size_preset(symbol, pitch, height) for symbol, pitch, height in _SIZE_TABLE_MM
)


#: Shipped starting points. Unlike a captured preset these are partial - each
#: sets only the fields that define it, so applying one changes nothing else.
GENERAL_PRESETS: Final[tuple[Preset, ...]] = (
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




#: Menu group holding reader-specific optics.
READER_GROUP: Final[str] = "Reader"


def _reader_preset(
    name: str,
    summary: str,
    *,
    source: str,
    fov_h_deg: float,
    fov_v_deg: float,
    dof_min_mm: float,
    dof_max_mm: float,
    sensor_px_h: int,
    codes_in_view: int = 1,
    frame_interval_ms: float = 20.0,
    exposure_us: int = 1000,
) -> Preset:
    """One reader, from its published specification.

    `source` is required, not optional. These are the only vendor figures in
    the project, and the module they feed states plainly that it invents none -
    so every one of them has to be traceable to the page it came from and
    checkable against the datasheet of the unit actually bought. Every value
    stays user-editable afterwards.

    To add a reader, add a call below. Nothing else needs changing: it appears
    in the Presets menu under its group, and the validation rules will report
    whether it can cover the configured geometry.
    """
    return _built_in(
        name,
        f"{summary}\n\nFigures from {source}. Confirm against the datasheet of "
        f"the unit you buy.",
        group=READER_GROUP,
        scanner={
            "fov_angle_deg": fov_h_deg,
            "fov_vertical_deg": fov_v_deg,
            "dof_min_mm": dof_min_mm,
            "dof_max_mm": dof_max_mm,
            "sensor_px_h": sensor_px_h,
            "min_codes_in_view": codes_in_view,
            # Frame rate and exposure belong to the reader as much as its optics
            # do, and both bound how fast the axis can run past the strip.
            "frame_interval_ms": frame_interval_ms,
            "exposure_us": exposure_us,
        },
    )


READER_PRESETS: Final[tuple[Preset, ...]] = (
    _reader_preset(
        "Newland NLS-NVF230-SR",
        "1280 x 800 sensor, 48.5 x 30.7 degree view, focuses 50-200 mm, 50 "
        "frames a second. A general-purpose fixed scanner: it reads one code at "
        "a time, so position steps in whole spacings and one damaged code loses "
        "it until the next.\n\n"
        "The view angles are confirmed by the user guide's own worked example "
        "(p.30): at a 100 mm mounting distance its selection tool reports a "
        "90 x 55 mm window, which is 48.46 x 30.75 degrees. The focus range is "
        "the product page's figure and is the softer number - the same worked "
        "example gives a much wider 0-248 mm for a 10 mil code, because depth of "
        "field grows with code size. Run Newland's NSet selection tool at your "
        "own module size before trusting either end of it",
        source="newlandaidc.com NVF230 product page; angles cross-checked "
        "against the NLS-NVF230 user guide p.30",
        fov_h_deg=48.5,
        fov_v_deg=30.7,
        dof_min_mm=50.0,
        dof_max_mm=200.0,
        sensor_px_h=1280,
        frame_interval_ms=20.0,
        exposure_us=1000,
    ),
)


#: Menu group holding printer resolutions.
PRINTER_GROUP: Final[str] = "Printer"


def _printer_preset(dpi: int, summary: str) -> Preset:
    """One printer resolution class.

    Generic by resolution rather than by model, deliberately: the printer is
    not yet chosen, and the resolution alone carries everything the solver
    needs - the dot size that sets the module floor and the dot grid. Three of
    these side by side is itself the purchasing comparison. A named-model
    preset (max print length, roll width) can join them the day a machine is
    picked, exactly as readers join READER_PRESETS.
    """
    dot_mm = 25.4 / dpi
    return _built_in(
        f"Generic {dpi} dpi label printer",
        f"{summary}\n\nOne dot is {dot_mm:.4f} mm, so a five-dot module is "
        f"{5 * dot_mm:.3f} mm and the smallest clean code (10 modules) is "
        f"{50 * dot_mm:.2f} mm.",
        group=PRINTER_GROUP,
        printer={"dpi": dpi},
    )


PRINTER_PRESETS: Final[tuple[Preset, ...]] = (
    _printer_preset(
        203,
        "The workhorse resolution. Coarsest dot, which sounds worse and is "
        "usually better here: 1 mm modules land almost exactly on 8 dots, and "
        "thermal printers at 203 dpi print the longest single pieces - "
        "typically metres, where 600 dpi machines manage less than one.",
    ),
    _printer_preset(
        300,
        "The middle ground. Finer codes than 203 dpi when space is tight; "
        "shorter maximum piece length on typical hardware.",
    ),
    _printer_preset(
        600,
        "The finest common resolution. Only needed when the code must be very "
        "small; typical hardware prints under a metre in one piece at this "
        "setting, so a long strip means splices.",
    ),
    _built_in(
        "Zebra ZD230t (203 dpi)",
        "Zebra's entry thermal-transfer desktop printer: 203 dpi (one dot is "
        "0.125 mm), 104 mm print width, media 25.4-112 mm wide, and a firmware "
        "maximum of 990 mm per printed piece - this preset caps the continuous "
        "piece length to match, so a long strip splits into printable rolls "
        "with splice boundaries at the joints.\n\n"
        "Use the thermal-transfer 't' variant with resin ribbon on polyester "
        "for a durable strip; the direct-thermal 'd' variant fades. Print via "
        "the ZDesigner driver at exactly 100 %, or use Export ZPL to bypass "
        "the driver entirely - the dots are then generated by AOPS at 203 dpi "
        "and nothing downstream can rescale them.\n\n"
        "Source: Zebra ZD230 spec sheet (zebra.com).",
        group=PRINTER_GROUP,
        printer={"dpi": 203, "max_label_length_mm": 990.0},
        output={"continuous_max_length_mm": 990.0},
    ),
)


#: Everything offered in the Presets menu.
BUILT_IN_PRESETS: Final[tuple[Preset, ...]] = (
    GENERAL_PRESETS + SIZE_PRESETS + READER_PRESETS + PRINTER_PRESETS
)
