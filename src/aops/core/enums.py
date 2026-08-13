"""Enumerations used across the configuration model.

All of these are `StrEnum` so that a saved `.aops` project file is readable and
diffs cleanly in version control - commissioning data gets committed alongside
PLC source, and an engineer reviewing a change should see
``"symbology": "datamatrix_ecc200"`` rather than ``"symbology": 0``.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Symbology(StrEnum):
    """Supported and reserved symbol types.

    Only DATA_MATRIX and QR are implemented. The remaining members exist so a
    project file can *name* them and be told clearly that they are unavailable,
    rather than silently falling back to a different symbology - see
    `aops.symbols.placeholders`.
    """

    DATA_MATRIX = "datamatrix_ecc200"
    QR = "qr"
    CODE128 = "code128"
    CODE39 = "code39"
    AZTEC = "aztec"

    @property
    def display_name(self) -> str:
        return {
            Symbology.DATA_MATRIX: "Data Matrix ECC200",
            Symbology.QR: "QR Code",
            Symbology.CODE128: "Code 128",
            Symbology.CODE39: "Code 39",
            Symbology.AZTEC: "Aztec",
        }[self]

    @property
    def implemented(self) -> bool:
        return self in (Symbology.DATA_MATRIX, Symbology.QR)


class QrEcc(StrEnum):
    """QR error-correction level."""

    L = "L"
    M = "M"
    Q = "Q"
    H = "H"


class PitchMode(StrEnum):
    """How an index maps onto physical distance when ``increment != 1``.

    This distinction is safety-relevant. Printing indices 0, 3, 6 into
    *contiguous* 25 mm cells puts index 6 at 50 mm, not 150 mm. A PLC given the
    wrong formula drives the axis to the wrong place.

    PER_CELL
        Cells are contiguous; position is derived from the cell ordinal.
        ``P = origin + dir * ((index - start) // increment) * pitch``
    PER_INDEX
        Blank cells are inserted for skipped indices, preserving the literal
        ``P = Index * Pitch`` relationship at the cost of blank tape.
        ``P = origin + dir * (index - start) * pitch``
    """

    PER_CELL = "per_cell"
    PER_INDEX = "per_index"


class Direction(StrEnum):
    """Whether position increases or decreases with index."""

    FORWARD = "forward"
    REVERSE = "reverse"


class Datum(StrEnum):
    """Which feature of a cell the reported position refers to.

    Changing this shifts every position by the same constant, so it folds into
    ``origin_mm`` and never changes the position *formula*. It therefore affects
    only the mounting diagram on the installation guide.
    """

    SYMBOL_CENTRE = "symbol_centre"
    CELL_LEADING_EDGE = "cell_leading_edge"


class LrMarginMode(StrEnum):
    """Resolves the over-determination between pitch, symbol size and margin.

    ``pitch = symbol + 2 * margin_lr`` has three variables and two degrees of
    freedom. One of them must be derived.

    DERIVED_FROM_PITCH
        Pitch and symbol size are authoritative; margin is computed (default).
    DRIVES_PITCH
        Symbol size and margin are authoritative; pitch is computed.
    """

    DERIVED_FROM_PITCH = "derived_from_pitch"
    DRIVES_PITCH = "drives_pitch"


class PayloadSource(StrEnum):
    """What the symbol actually encodes.

    POSITION_MM
        The absolute position, scaled by ``unit_scale`` and zero padded. This is
        the implemented behaviour: the strip is self-describing, so a scanner
        reads a real machine coordinate rather than an index the PLC must then
        multiply.
    INDEX / CUSTOM
        Reserved extension points; not implemented.
    """

    POSITION_MM = "position_mm"
    INDEX = "index"
    CUSTOM = "custom"


class PaperPreset(StrEnum):
    """ISO sheet sizes, label-printer roll widths, and a user-defined size.

    The roll entries exist because a label printer is arguably the *right*
    device for this job rather than a concession. A thermal-transfer label
    printer running continuous polyester with a resin ribbon produces exactly
    the industrial tape this tool is designed around, and because the media is
    continuous it removes the splice problem altogether - no page boundaries,
    so no cutting accuracy to worry about and no per-tile datum alignment.

    Roll widths are stated as *printable* width, which is what constrains the
    artwork; media is typically a few millimetres wider. The nominal length of
    one metre is only the tile size used when tiled output is selected, and is
    irrelevant to a continuous export.
    """

    A4 = "A4"
    A3 = "A3"
    A2 = "A2"
    A1 = "A1"
    A0 = "A0"
    ROLL_2IN = "roll_2in"
    ROLL_3IN = "roll_3in"
    ROLL_4IN = "roll_4in"
    ROLL_6IN = "roll_6in"
    ROLL_8IN = "roll_8in"
    CUSTOM = "custom"

    @property
    def portrait_mm(self) -> tuple[float, float]:
        """(width, height) in mm for portrait orientation. CUSTOM returns A4."""
        return {
            PaperPreset.A4: (210.0, 297.0),
            PaperPreset.A3: (297.0, 420.0),
            PaperPreset.A2: (420.0, 594.0),
            PaperPreset.A1: (594.0, 841.0),
            PaperPreset.A0: (841.0, 1189.0),
            PaperPreset.ROLL_2IN: (48.0, 1000.0),
            PaperPreset.ROLL_3IN: (72.0, 1000.0),
            PaperPreset.ROLL_4IN: (104.0, 1000.0),
            PaperPreset.ROLL_6IN: (152.0, 1000.0),
            PaperPreset.ROLL_8IN: (203.0, 1000.0),
            PaperPreset.CUSTOM: (210.0, 297.0),
        }[self]

    @property
    def is_roll(self) -> bool:
        """True for continuous label-printer roll media."""
        return self.name.startswith("ROLL_")

    @property
    def roll_width_mm(self) -> float:
        """Printable width across the roll. Zero for sheet media."""
        return self.portrait_mm[0] if self.is_roll else 0.0

    @property
    def display_name(self) -> str:
        if self is PaperPreset.CUSTOM:
            return "Custom"
        if self.is_roll:
            inches = self.name.removeprefix("ROLL_").removesuffix("IN")
            return f'Label roll {inches}" ({self.roll_width_mm:.0f} mm printable)'
        return self.value


class Climate(StrEnum):
    """Where the machine stands, as a view of the environment swing fields.

    "Humidity swing 40 %" is a question for a meteorologist; "which room does
    the machine stand in" anyone can answer. Like `PrintStyle`, this is not a
    stored field - it is derived from `rh_swing_percent` and
    `temp_swing_deg_c` by `detect_climate`, and selecting one writes them, so
    the plain choice and the expert numbers can never disagree. Hand-tuned
    swings simply read as CUSTOM.
    """

    CONDITIONED = "conditioned"
    FACTORY = "factory"
    HARSH = "harsh"
    CUSTOM = "custom"

    @property
    def display_name(self) -> str:
        return {
            Climate.CONDITIONED: "Climate-controlled room",
            Climate.FACTORY: "Factory floor",
            Climate.HARSH: "Unconditioned / harsh",
            Climate.CUSTOM: "Custom",
        }[self]

    @property
    def description(self) -> str:
        return {
            Climate.CONDITIONED: (
                "Heated and cooled space: metrology room, lab, climate-controlled "
                "workshop. Assumes 10 degC and 20 %RH of seasonal swing."
            ),
            Climate.FACTORY: (
                "A typical production hall: heated but not tightly controlled. "
                "Assumes 30 degC and 40 %RH of swing - the shipped default."
            ),
            Climate.HARSH: (
                "Unconditioned shed, washdown area, near loading doors or under a "
                "roof outdoors. Assumes 50 degC and 70 %RH of swing."
            ),
            Climate.CUSTOM: (
                "The swing numbers were set by hand and match no named "
                "environment. Set them in the Advanced media section."
            ),
        }[self]


class PrintStyle(StrEnum):
    """How much page furniture is printed around the symbols.

    The tool's defaults produce a commissioning document: ruler, calibration
    bar, header, footer, registration and cut marks, all of which exist to make
    the strip verifiable. That is the right output for a strip going onto a
    machine, and the wrong output for a design proof or for stock you have
    already calibrated and only want clean artwork from.

    This is a *view* of the individual furniture switches rather than a stored
    field of its own. Storing both would let the two disagree; instead the
    style is derived from the switches by `detect_style`, and selecting one
    sets them. A configuration that matches no preset simply reads as CUSTOM.
    """

    PLAIN = "plain"
    LABELLED = "labelled"
    ENGINEERING = "engineering"
    CUSTOM = "custom"

    @property
    def display_name(self) -> str:
        return {
            PrintStyle.PLAIN: "Plain - symbols only",
            PrintStyle.LABELLED: "Labelled - symbols and numbers",
            PrintStyle.ENGINEERING: "Engineering - full commissioning set",
            PrintStyle.CUSTOM: "Custom",
        }[self]

    @property
    def description(self) -> str:
        return {
            PrintStyle.PLAIN: (
                "Nothing but the symbols. No ruler, calibration bar, header, footer "
                "or marks. Use for design proofs and artwork - there is no printed "
                "means of checking the scale came out right."
            ),
            PrintStyle.LABELLED: (
                "Symbols with their position printed underneath, and nothing else. "
                "Readable by eye without the surrounding commissioning furniture."
            ),
            PrintStyle.ENGINEERING: (
                "Everything needed to install and verify the strip: calibration bar, "
                "ruler, absolute X range per sheet, registration and cut marks, and "
                "the installation guide."
            ),
            PrintStyle.CUSTOM: (
                "The switches below do not match any preset. Pick a style to reset "
                "them, or carry on - nothing is wrong with a custom combination."
            ),
        }[self]


class Orientation(StrEnum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class ContinuousStrategy(StrEnum):
    """How to emit a strip longer than the PDF page-size limit.

    USER_UNIT
        Shrink the MediaBox by a factor and declare ``/UserUnit`` (PDF 1.6+) so
        the page still measures true size. One page, no joins. Honoured by
        Acrobat 7+ and modern RIPs; the 200 mm calibration bar catches any RIP
        that ignores it.
    RAW_OVERSIZE
        Emit the true oversized MediaBox. Many large-format RIPs accept it;
        Acrobat will refuse or clamp it.
    SPLIT_ROLL
        Emit N single-page files each within the conformant limit. Universally
        safe, but the shop must splice.
    """

    USER_UNIT = "user_unit"
    RAW_OVERSIZE = "raw_oversize"
    SPLIT_ROLL = "split_roll"


class SpliceMode(StrEnum):
    """How adjacent tiles meet."""

    BUTT = "butt"
    OVERLAP = "overlap"


class PageScope(StrEnum):
    """Whether an element appears once or on every page."""

    FIRST_PAGE = "first_page"
    EVERY_PAGE = "every_page"


class VerifyMode(StrEnum):
    """How much of an export is decode-verified before the file is written.

    Verification re-renders each extracted module matrix and runs it back
    through a real Data Matrix decoder. At roughly 10-40 ms per symbol it is far
    too slow for every code on a long strip, and exactly right for a sample.
    """

    OFF = "off"
    SAMPLE = "sample"
    ALL = "all"


class RulerPosition(StrEnum):
    ABOVE = "above"
    BELOW = "below"


class HrPosition(StrEnum):
    """Where the human-readable text sits relative to the symbol."""

    ABOVE = "above"
    BELOW = "below"


class PrintMethod(StrEnum):
    """Print process, which determines durability and media compatibility."""

    LASER = "laser"
    INKJET = "inkjet"
    THERMAL_TRANSFER = "thermal_transfer"
    DIRECT_THERMAL = "direct_thermal"
    SIGN_SHOP = "sign_shop"

    @property
    def display_name(self) -> str:
        return {
            PrintMethod.LASER: "Laser (toner)",
            PrintMethod.INKJET: "Inkjet",
            PrintMethod.THERMAL_TRANSFER: "Thermal transfer (label printer)",
            PrintMethod.DIRECT_THERMAL: "Direct thermal (no ribbon)",
            PrintMethod.SIGN_SHOP: "Sign shop / large format",
        }[self]

    @property
    def uses_ribbon(self) -> bool:
        """Direct thermal marks heat-sensitive stock and takes no ribbon."""
        return self is PrintMethod.THERMAL_TRANSFER


class Ribbon(StrEnum):
    """Thermal-transfer ribbon chemistry.

    Wax scratches off synthetic stock within weeks in a machine environment;
    resin on polyester is the 5+ year industrial choice.
    """

    NONE = "none"
    WAX = "wax"
    WAX_RESIN = "wax_resin"
    RESIN = "resin"


class Media(StrEnum):
    """Substrate. This choice dominates 1:1 dimensional accuracy.

    Paper moves roughly 3 % between 20 % and 80 % relative humidity. Over a
    10.5 m strip that is ~315 mm of error - three orders of magnitude worse than
    the sub-millimetre accuracy a positioning system exists to provide. Polyester
    film is ~0.006 % over the same range.
    """

    PAPER = "paper"
    SYNTHETIC = "synthetic"
    POLYESTER = "polyester"
    VINYL = "vinyl"

    @property
    def display_name(self) -> str:
        return {
            Media.PAPER: "Paper",
            Media.SYNTHETIC: "Synthetic paper",
            Media.POLYESTER: "Polyester film",
            Media.VINYL: "Vinyl",
        }[self]

    @property
    def dim_stability_pct_per_rh(self) -> float:
        """Dimensional change in percent per percentage point of relative humidity.

        Derived from published 20 %->80 %RH figures (a 60-point swing):
        paper ~3 % -> 0.05 %/%RH; coated film ~0.5 % -> 0.0083 %/%RH;
        polyester film base ~0.006 % -> 0.0001 %/%RH.
        """
        return {
            Media.PAPER: 0.05,
            Media.SYNTHETIC: 0.0083,
            Media.POLYESTER: 0.0001,
            Media.VINYL: 0.0050,
        }[self]

    @property
    def cte_ppm_per_c(self) -> float:
        """Linear coefficient of thermal expansion, in ppm per degree Celsius.

        Published ranges for the film bases in question: BoPET/polyester
        15-20, polypropylene-based synthetic stock 60-80, plasticised PVC
        50-80. The midpoint of each is used.

        For polyester this term is the *larger* of the two substrate effects on
        a long strip: 17 ppm over a 30 C swing is 0.051 %, against 0.004 % for
        a 40-point humidity swing. Temperature is not the second-order effect
        it is often assumed to be.
        """
        return {
            Media.PAPER: 15.0,
            Media.SYNTHETIC: 70.0,
            Media.POLYESTER: 17.0,
            Media.VINYL: 70.0,
        }[self]


class FrameMaterial(StrEnum):
    """What the strip is mounted to.

    Only the *difference* between the substrate's expansion and the frame's
    reaches the position reading, so the frame is as much a part of the error
    budget as the tape. An aluminium extrusion at 23 ppm expands faster than
    polyester at 17; structural steel at 12 expands slower. The sign of the
    error flips between the two.
    """

    STEEL = "steel"
    STAINLESS = "stainless"
    ALUMINIUM = "aluminium"
    CAST_IRON = "cast_iron"
    GRANITE = "granite"

    @property
    def display_name(self) -> str:
        return {
            FrameMaterial.STEEL: "Mild / structural steel",
            FrameMaterial.STAINLESS: "Stainless steel (304)",
            FrameMaterial.ALUMINIUM: "Aluminium",
            FrameMaterial.CAST_IRON: "Cast iron",
            FrameMaterial.GRANITE: "Granite",
        }[self]

    @property
    def cte_ppm_per_c(self) -> float:
        """Linear coefficient of thermal expansion, in ppm per degree Celsius."""
        return {
            FrameMaterial.STEEL: 12.0,
            FrameMaterial.STAINLESS: 17.0,
            FrameMaterial.ALUMINIUM: 23.0,
            FrameMaterial.CAST_IRON: 11.0,
            FrameMaterial.GRANITE: 6.0,
        }[self]


class TapeMounting(StrEnum):
    """How the strip is fixed along its length.

    This decides whether thermal expansion reaches the position reading at all,
    and it is the single most consequential mounting choice.

    CONTINUOUS_BOND
        Bonded along its whole length. The adhesive forces the tape to follow
        the frame, so a code stays over the machine feature it was aligned to
        and the thermal term very largely cancels. The strain does not vanish -
        it is carried by the adhesive - so a large CTE mismatch becomes a bond
        durability problem instead of a position error.
    END_ANCHORED
        Fixed at one end (or in a channel) and free to move elsewhere, which is
        the conventional way to mount a long tape. The tape now expands at its
        own rate and the full differential reaches the reading.
    """

    CONTINUOUS_BOND = "continuous_bond"
    END_ANCHORED = "end_anchored"

    @property
    def display_name(self) -> str:
        return {
            TapeMounting.CONTINUOUS_BOND: "Bonded along full length",
            TapeMounting.END_ANCHORED: "Anchored at one end",
        }[self]


class Severity(IntEnum):
    """Validation severity. Ordered, so `max()` finds the worst finding."""

    INFO = 0
    WARNING = 1
    ERROR = 2
    FATAL = 3

    @property
    def label(self) -> str:
        return self.name.capitalize()


class FontRole(StrEnum):
    """Backend-agnostic font selection.

    Layout code names a role; each rendering backend resolves it to a concrete
    font. Every measured string in this application (indices, distances, page
    numbers) is monospaced by design, which is what makes the core text
    measurement fallback exact rather than approximate.
    """

    MONO = "mono"
    MONO_BOLD = "mono_bold"
    SANS = "sans"
    SANS_BOLD = "sans_bold"


class Anchor(StrEnum):
    """Text anchoring."""

    BASELINE_LEFT = "baseline_left"
    BASELINE_CENTRE = "baseline_centre"
    BASELINE_RIGHT = "baseline_right"


class LineCap(StrEnum):
    BUTT = "butt"
    ROUND = "round"
    SQUARE = "square"


class SegmentKind(StrEnum):
    """Atomic pieces of the strip along its length.

    ``CELL`` segments are indivisible - the packer may never split one across a
    page boundary. ``LEAD``/``TRAIL``/``BLANK`` contain no ink and may be cut
    anywhere. That single distinction is what guarantees splice safety, and it
    is why future features (dual track, fiducials, CRC blocks) need only
    register as atomic segments to inherit the guarantee.
    """

    LEAD = "lead"
    CELL = "cell"
    TRAIL = "trail"
    BLANK = "blank"
